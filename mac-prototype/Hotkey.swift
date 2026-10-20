import AppKit
import ApplicationServices

struct VoiceShortcut:Codable {
    var keyCode:Int
    var modifiers:UInt64
    var label:String
    var mouseButton:Int? = nil
    static let standard=VoiceShortcut(keyCode:61,modifiers:0,label:"右 Option")
    static let modifierKeys:Set<Int>=[54,55,56,58,59,60,61,62]
    static let functionKeys:Set<Int>=[122,120,99,118,96,97,98,100,101,109,103,111]
    static let flagMask:UInt64=0x1e0000
    var valid:Bool {
        if let button=mouseButton{return (3...31).contains(button) && keyCode == -1 && modifiers==0 && !label.isEmpty && label.count<=60}
        return keyCode>=0 && keyCode<=126 && !label.isEmpty && label.count<=60 && modifiers & ~Self.flagMask == 0 &&
        (Self.modifierKeys.contains(keyCode) ? modifiers==0 : (modifiers != 0 || Self.functionKeys.contains(keyCode)))
    }
}

final class RightOptionMonitor {
    private var tap:CFMachPort?
    private var source:CFRunLoopSource?
    private var activationObserver:NSObjectProtocol?
    private var gesture=OptionGesture()
    private var armed=false,used=false
    var shortcut=VoiceShortcut.standard {didSet{gesture.reset();armed=false;used=false}}
    var suspended=false {didSet{gesture.reset();armed=false;used=false}}
    var onToggle:(()->Void)?
    var onCancel:(()->Void)?
    var shouldCancel:(()->Bool)?
    var onMouseCapture:((Int)->Void)?
    private var canFilter=false
    // A revision only: no key, mouse position or typed content is retained.
    private(set) var inputRevision:UInt64=0
    var enabled:Bool{tap != nil}
    static var authorized:Bool{CGPreflightListenEventAccess()}
    func requestPermission(){_ = CGRequestListenEventAccess()}
    private func fire(){DispatchQueue.main.async { [weak self] in self?.onToggle?() }}
    @discardableResult func handle(_ type:CGEventType,_ event:CGEvent)->Bool {
        if event.getIntegerValueField(.eventSourceUserData)==AutoPaste.eventMarker{return false}
        let button=Int(event.getIntegerValueField(.mouseEventButtonNumber))
        let key=Int(event.getIntegerValueField(.keyboardEventKeycode))
        let shortcutKey=type == .keyDown && key==shortcut.keyCode && event.flags.rawValue & VoiceShortcut.flagMask == shortcut.modifiers
        let shortcutMouse=(type == .otherMouseDown || type == .otherMouseUp) && button==shortcut.mouseButton
        // Releasing modifiers or tapping the dictation key does not move a caret.
        // Real typing, clicks, scrolling and activation still invalidate delivery.
        if (type == .keyDown && !shortcutKey) || ([.leftMouseDown,.rightMouseDown,.otherMouseDown,.scrollWheel].contains(type) && !shortcutMouse) {inputRevision &+= 1}
        if suspended {
            if type == .otherMouseUp && (3...31).contains(button){DispatchQueue.main.async{[weak self] in self?.onMouseCapture?(button)}}
            return (type == .otherMouseDown || type == .otherMouseUp) && (3...31).contains(button)
        }
        if type == .keyDown && key==53 && event.getIntegerValueField(.keyboardEventAutorepeat)==0 && shouldCancel?()==true {
            DispatchQueue.main.async{[weak self] in self?.onCancel?()};return true
        }
        if let expected=shortcut.mouseButton {
            if type == .otherMouseDown && button==expected{armed=true;used=false}
            else if type == .otherMouseUp && button==expected{let fireNow=armed && !used;armed=false;used=false;if fireNow{fire()}}
            else if type == .keyDown || type == .leftMouseDown || type == .rightMouseDown || type == .otherMouseDown{used=true}
            return (type == .otherMouseDown || type == .otherMouseUp) && button==expected
        }
        guard type == .keyDown || type == .keyUp || type == .flagsChanged else{return false}
        if VoiceShortcut.modifierKeys.contains(shortcut.keyCode) {
            if type == .flagsChanged && key==shortcut.keyCode {
                let masks:[Int:UInt64]=[54:0x10,55:0x08,56:0x02,58:0x20,59:0x01,60:0x04,61:0x40,62:0x2000]
                let down=event.flags.rawValue & (masks[key] ?? 0) != 0
                if down {
                    _=gesture.rightOption(true)
                    let expected:[Int:UInt64]=[54:0x100000,55:0x100000,56:0x20000,60:0x20000,58:0x80000,61:0x80000,59:0x40000,62:0x40000]
                    if event.flags.rawValue & VoiceShortcut.flagMask != expected[key] {gesture.otherInput()}
                } else if gesture.rightOption(false) {fire()}
            } else if type == .keyDown || type == .flagsChanged {gesture.otherInput()}
        } else if type == .keyDown {
            if key==shortcut.keyCode && event.getIntegerValueField(.keyboardEventAutorepeat)==0 && event.flags.rawValue & VoiceShortcut.flagMask == shortcut.modifiers {
                armed=true;used=false
            } else if key != shortcut.keyCode {used=true}
        } else if type == .keyUp && key==shortcut.keyCode {
            let shouldFire=armed && !used;armed=false;used=false;if shouldFire{fire()}
        }
        return false
    }
    func start()->Bool {
        guard tap==nil else{return true};guard Self.authorized else{return false}
        let types:[CGEventType]=[.flagsChanged,.keyDown,.keyUp,.leftMouseDown,.rightMouseDown,.otherMouseDown,.otherMouseUp,.scrollWheel]
        let mask=types.reduce(CGEventMask(0)){$0 | (1 << $1.rawValue)}
        let callback:CGEventTapCallBack={_,type,event,context in
            let owner=Unmanaged<RightOptionMonitor>.fromOpaque(context!).takeUnretainedValue()
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                owner.inputRevision &+= 1
                if let tap=owner.tap{CGEvent.tapEnable(tap:tap,enable:true)}
            } else if owner.handle(type,event) && owner.canFilter {return nil}
            return Unmanaged.passUnretained(event)
        }
        canFilter=AXIsProcessTrusted()
        guard let port=CGEvent.tapCreate(tap:.cgSessionEventTap,place:.headInsertEventTap,options:canFilter ? .defaultTap : .listenOnly,eventsOfInterest:CGEventMask(mask),callback:callback,userInfo:Unmanaged.passUnretained(self).toOpaque()) else{return false}
        tap=port;source=CFMachPortCreateRunLoopSource(kCFAllocatorDefault,port,0)
        CFRunLoopAddSource(CFRunLoopGetMain(),source,.commonModes);CGEvent.tapEnable(tap:port,enable:true)
        inputRevision &+= 1
        activationObserver=NSWorkspace.shared.notificationCenter.addObserver(forName:NSWorkspace.didActivateApplicationNotification,object:nil,queue:.main){[weak self] _ in self?.inputRevision &+= 1}
        return true
    }
    func stop(){if let observer=activationObserver{NSWorkspace.shared.notificationCenter.removeObserver(observer);activationObserver=nil};inputRevision &+= 1;if let tap=tap{CGEvent.tapEnable(tap:tap,enable:false);CFMachPortInvalidate(tap)};if let source=source{CFRunLoopRemoveSource(CFRunLoopGetMain(),source,.commonModes)};tap=nil;source=nil;gesture.reset();armed=false}
    deinit{stop()}
}
