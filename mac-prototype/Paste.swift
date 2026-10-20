import AppKit
import ApplicationServices

struct ClipboardLeaseToken:Equatable {let generation:Int;let changeCount:Int}

final class ClipboardLease {
    private let board:NSPasteboard
    private var original:[[(NSPasteboard.PasteboardType,Data)]]?
    private var ownedCount:Int?
    private var generation=0
    init(board:NSPasteboard = .general){self.board=board}
    func stage(_ text:String)->ClipboardLeaseToken? {
        if original != nil,board.changeCount != ownedCount {original=nil;ownedCount=nil}
        if original == nil {
            let before=board.changeCount
            var rows=[[(NSPasteboard.PasteboardType,Data)]]()
            for item in board.pasteboardItems ?? [] {
                var row=[(NSPasteboard.PasteboardType,Data)]()
                for type in item.types {
                    guard let data=item.data(forType:type) else{return nil}
                    row.append((type,data))
                }
                rows.append(row)
            }
            guard board.changeCount==before else{return nil}
            original=rows
        }
        generation+=1
        board.clearContents()
        guard board.setString(text,forType:.string) else {
            ownedCount=board.changeCount;restoreOwnedNow();return nil
        }
        ownedCount=board.changeCount
        return ClipboardLeaseToken(generation:generation,changeCount:board.changeCount)
    }
    @discardableResult func restore(_ token:ClipboardLeaseToken)->Bool {
        guard token.generation==generation,let original=original else{return false}
        guard board.changeCount==token.changeCount else{abandon();return false}
        var items=[NSPasteboardItem]()
        for row in original {
            let item=NSPasteboardItem()
            for (type,data) in row {item.setData(data,forType:type)}
            items.append(item)
        }
        board.clearContents()
        let ok=items.isEmpty || board.writeObjects(items)
        abandon();return ok
    }
    func scheduleRestore(_ token:ClipboardLeaseToken,after delay:Double=1.5) {
        DispatchQueue.main.asyncAfter(deadline:.now()+delay) {[weak self] in _=self?.restore(token)}
    }
    func restoreOwnedNow() {if let count=ownedCount {_=restore(ClipboardLeaseToken(generation:generation,changeCount:count))}}
    func abandon(){generation+=1;original=nil;ownedCount=nil}
}

// Custom editors may omit AX selection/focus. Use the stop-time window and an
// uninterrupted input revision, without an app-name allowlist or content reads.
struct WindowPasteGuard {
    let pid:pid_t,windowID:CGWindowID,revision:UInt64
    init?(pid:pid_t,windowID:CGWindowID?,revision:UInt64?) {
        guard pid>0,let windowID=windowID,windowID != 0,let revision=revision else{return nil}
        self.pid=pid;self.windowID=windowID;self.revision=revision
    }
    func matches(pid:pid_t?,windowID:CGWindowID?,revision:UInt64?)->Bool {
        pid==self.pid && windowID==self.windowID && revision==self.revision
    }
}

struct PasteTarget {
    let pid:pid_t
    let element:AXUIElement?
    let selection:CFRange?
    let windowGuard:WindowPasteGuard?
    let inputRevision:UInt64?
    let currentInputRevision:()->UInt64?
    let windowID:CGWindowID?
    private static func frontWindow(_ pid:pid_t)->CGWindowID? {
        // Window metadata only. No pixels, titles, chat contents or screenshot permission.
        guard let rows=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] else{return nil}
        for row in rows where (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value==pid && (row[kCGWindowLayer as String] as? NSNumber)?.intValue==0 {
            guard (row[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1 > 0,
                  let id=(row[kCGWindowNumber as String] as? NSNumber)?.uint32Value,id != 0 else{continue}
            return id
        }
        return nil
    }
    private static func focused(_ pid:pid_t)->AXUIElement? {
        let app=AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app,0.2)
        var value:CFTypeRef?
        guard AXUIElementCopyAttributeValue(app,kAXFocusedUIElementAttribute as CFString,&value) == .success,
              let value=value,CFGetTypeID(value)==AXUIElementGetTypeID() else{return nil}
        let element=value as! AXUIElement
        AXUIElementSetMessagingTimeout(element,0.2)
        return element
    }
    private static func range(_ element:AXUIElement)->CFRange? {
        var value:CFTypeRef?
        guard AXUIElementCopyAttributeValue(element,kAXSelectedTextRangeAttribute as CFString,&value) == .success,
              let value=value,CFGetTypeID(value)==AXValueGetTypeID() else{return nil}
        var range=CFRange()
        return AXValueGetValue(value as! AXValue,.cfRange,&range) ? range : nil
    }
    private static func secure(_ element:AXUIElement)->Bool {
        var value:CFTypeRef?
        return AXUIElementCopyAttributeValue(element,kAXSubroleAttribute as CFString,&value) == .success && (value as? String)=="AXSecureTextField"
    }
    static func capture(inputRevision:@escaping()->UInt64? = {nil})->PasteTarget? {
        guard AXIsProcessTrusted(),let app=NSWorkspace.shared.frontmostApplication,app.processIdentifier != ProcessInfo.processInfo.processIdentifier else{return nil}
        let pid=app.processIdentifier,revision=inputRevision(),element=focused(pid),selection=element.flatMap{range($0)},windowID=frontWindow(pid)
        if let element=element,secure(element){return nil}
        let fallback:WindowPasteGuard? = selection == nil ? WindowPasteGuard(pid:pid,windowID:windowID,revision:revision) : nil
        guard element != nil || fallback != nil else{return nil}
        return PasteTarget(pid:pid,element:element,selection:selection,windowGuard:fallback,inputRevision:revision,currentInputRevision:inputRevision,windowID:windowID)
    }
    func stillFocused()->Bool {
        let frontPID=NSWorkspace.shared.frontmostApplication?.processIdentifier
        guard frontPID==pid else{return false}
        if let before=inputRevision, currentInputRevision() != before{return false}
        if let guardValue=windowGuard {
            if let current=Self.focused(pid),Self.secure(current){return false}
            return guardValue.matches(pid:frontPID,windowID:Self.frontWindow(pid),revision:currentInputRevision())
        }
        guard let element=element,let current=Self.focused(pid),CFEqual(current,element) else{return false}
        if let before=selection {
            guard let now=Self.range(current),now.location==before.location,now.length==before.length else{return false}
        }
        return true
    }
    // Only our immediately preceding insertion may rebase a queued selection.
    // An intervening click, keystroke, window change or different editor refuses it.
    func followingInsertion(into previous:PasteTarget)->PasteTarget? {
        guard let windowID=windowID,windowID==previous.windowID,pid==previous.pid,
              let revision=inputRevision,revision==previous.inputRevision,currentInputRevision()==revision,
              selection?.location==previous.selection?.location,selection?.length==previous.selection?.length,
              (element==nil && previous.element==nil) || (element != nil && previous.element != nil && CFEqual(element!,previous.element!)),
              let now=Self.capture(inputRevision:currentInputRevision),now.pid==pid,now.windowID==windowID,now.inputRevision==revision else{return nil}
        if let element=element {guard let current=now.element,CFEqual(element,current) else{return nil}}
        return now
    }
}

struct DeliverySettings {
    var autoPaste=true,keepTranscription=true
    init(autoPaste:Bool=true,keepTranscription:Bool=true){self.autoPaste=autoPaste;self.keepTranscription=keepTranscription}
    static func read(_ directory:URL)->DeliverySettings {
        guard let data=try? Data(contentsOf:directory.appendingPathComponent("runtime-settings.json")),let v=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] else{return DeliverySettings()}
        return DeliverySettings(autoPaste:v["auto_paste"] as? Bool ?? true,keepTranscription:v["keep_transcription"] as? Bool ?? true)
    }
}

enum PasteOutcome:Equatable {
    case posted,copied,emptyText,needsPermission,targetUnavailable,targetChanged,clipboardUnavailable,eventUnavailable
    var message:String {
        switch self {
        case .posted:return "已完成"
        case .copied:return "已复制"
        case .emptyText:return "未识别到文字"
        case .needsPermission:return "文字已保留 · 需粘贴权限"
        case .targetUnavailable:return "文字已保留 · 未能定位输入位置"
        case .targetChanged:return "文字已保留 · 输入位置有变化"
        default:return "文字已保留 · 可手动复制"
        }
    }
}

final class AutoPaste {
    static let eventMarker:Int64=0x5848564f494345
    private let board:NSPasteboard
    let clipboard:ClipboardLease
    init(board:NSPasteboard = .general){self.board=board;clipboard=ClipboardLease(board:board)}
    private var cancelled=false
    static var authorized:Bool {AXIsProcessTrusted()}
    static func requestPermission(){let options=[kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String:true] as CFDictionary;_ = AXIsProcessTrustedWithOptions(options)}
    func copy(_ text:String)->Bool{clipboard.abandon();board.clearContents();return board.setString(text,forType:.string)}
    func paste(_ text:String,target:PasteTarget?,settings:DeliverySettings=DeliverySettings(autoPaste:true,keepTranscription:false),current:@escaping ()->Bool,completion:@escaping(PasteOutcome)->Void) {
        guard !cancelled else{return}
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else{completion(.emptyText);return}
        if !settings.autoPaste{completion(copy(text) ? .copied : .clipboardUnavailable);return}
        guard Self.authorized else{completion(.needsPermission);return}
        guard let target=target else{completion(.targetUnavailable);return}
        guard current(),target.stillFocused() else{completion(.targetChanged);return}
        waitForModifierRelease(text,target:target,settings:settings,current:current,completion:completion,deadline:Date().addingTimeInterval(0.8))
    }
    private func waitForModifierRelease(_ text:String,target:PasteTarget,settings:DeliverySettings,current:@escaping()->Bool,completion:@escaping(PasteOutcome)->Void,deadline:Date){
        guard !cancelled,current(),target.stillFocused() else{completion(.targetChanged);return}
        let held=CGEventSource.flagsState(.combinedSessionState).intersection([.maskCommand,.maskControl,.maskAlternate,.maskShift])
        if !held.isEmpty {
            guard Date()<deadline else{completion(.targetChanged);return}
            DispatchQueue.main.asyncAfter(deadline:.now()+0.02){[weak self] in self?.waitForModifierRelease(text,target:target,settings:settings,current:current,completion:completion,deadline:deadline)}
            return
        }
        guard let token=clipboard.stage(text) else{completion(.clipboardUnavailable);return}
        DispatchQueue.main.asyncAfter(deadline:.now()+0.03) { [weak self] in
            guard let self=self else{return}
            guard !self.cancelled,current(),target.stillFocused() else{self.clipboard.restoreOwnedNow();completion(.targetChanged);return}
            guard let source=CGEventSource(stateID:.privateState),
                  let down=CGEvent(keyboardEventSource:source,virtualKey:9,keyDown:true),
                  let up=CGEvent(keyboardEventSource:source,virtualKey:9,keyDown:false) else {
                self.clipboard.restoreOwnedNow();completion(.eventUnavailable);return
            }
            down.flags = .maskCommand;up.flags = .maskCommand
            down.setIntegerValueField(.eventSourceUserData,value:Self.eventMarker);up.setIntegerValueField(.eventSourceUserData,value:Self.eventMarker)
            down.postToPid(target.pid);up.postToPid(target.pid)
            if settings.keepTranscription{self.clipboard.abandon()}else{self.clipboard.scheduleRestore(token)}
            completion(.posted)
        }
    }
    func cancel(){cancelled=true;clipboard.restoreOwnedNow()}
}
