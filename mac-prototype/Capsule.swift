import AppKit

final class VoicePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
final class CapsuleBackground: NSView {
    var fill=NSColor(calibratedRed:0.137,green:0.153,blue:0.184,alpha:0.97)
    var border=NSColor.white.withAlphaComponent(0.11)
    override func draw(_ dirtyRect:NSRect) {
        fill.setFill()
        NSBezierPath(roundedRect:bounds,xRadius:22,yRadius:22).fill()
        border.setStroke()
        NSBezierPath(roundedRect:bounds.insetBy(dx:0.5,dy:0.5),xRadius:22,yRadius:22).stroke()
    }
}
final class WaveView:NSView {
    var color=NSColor(calibratedRed:0.58,green:0.87,blue:0.91,alpha:1)
    var rms=0.0 {didSet{needsDisplay=true}}
    var active=false {didSet{needsDisplay=true}}
    override func draw(_ dirtyRect:NSRect) {
        color.setFill()
        let scale=active ? max(0.08,min(1,pow(rms*9,0.6))) : 0.08
        for (i,ratio) in [0.35,0.6,0.9,0.65,1.0,0.7,0.4].enumerated() {
            let h=max(2,24*ratio*scale)
            NSBezierPath(roundedRect:NSRect(x:CGFloat(i)*5,y:(bounds.height-h)/2,width:3,height:h),xRadius:1.5,yRadius:1.5).fill()
        }
    }
}

final class Capsule {
    let panel:VoicePanel
    private let status=NSTextField(labelWithString:"准备好")
    private let time=NSTextField(labelWithString:"00:00")
    private let hint=NSTextField(labelWithString:"右 Option 开始")
    private let line=NSTextField(labelWithString:"点菜单栏麦克风开始，或启用右 Option")
    private let full=NSTextView()
    private let scroll=NSScrollView()
    private let wave=WaveView()
    private let dismiss=NSButton(title:"×",target:nil,action:nil)
    private let expand=NSButton(title:"⌄",target:nil,action:nil)
    private let copy=NSButton(title:"复制",target:nil,action:nil)
    private let retry=NSButton(title:"重试识别",target:nil,action:nil)
    private var expanded=false
    private var hideWork:DispatchWorkItem?
    private var theme=CapsuleThemeMode.initial
    private var appliedPalette:CapsulePalette?
    private var previewUntil=Date.distantPast
    var onCopy:(()->Void)?
    var onRetry:(()->Void)?
    var onDismiss:(()->Void)?
    init() {
        panel=VoicePanel(contentRect:NSRect(x:0,y:0,width:420,height:78),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
        panel.isFloatingPanel=true;panel.level = .floating;panel.hidesOnDeactivate=false
        panel.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary]
        panel.isOpaque=false;panel.backgroundColor = .clear;panel.hasShadow=true
        let bg=CapsuleBackground(frame:NSRect(x:0,y:0,width:420,height:78));bg.autoresizingMask=[.width,.height]
        panel.contentView=bg
        wave.frame=NSRect(x:17,y:44,width:35,height:26);wave.autoresizingMask=[.minYMargin];bg.addSubview(wave)
        for (label,font,color) in [(status,NSFont.systemFont(ofSize:12,weight:.medium),NSColor(calibratedWhite:0.86,alpha:1)),(time,NSFont.monospacedDigitSystemFont(ofSize:12,weight:.regular),NSColor(calibratedWhite:0.7,alpha:1)),(hint,NSFont.systemFont(ofSize:11),NSColor(calibratedWhite:0.87,alpha:1)),(line,NSFont.systemFont(ofSize:14),NSColor.white)] {
            label.font=font;label.textColor=color;label.backgroundColor = .clear;label.isBezeled=false
            label.cell?.lineBreakMode = .byTruncatingHead;label.autoresizingMask=[.minYMargin];bg.addSubview(label)
        }
        status.frame=NSRect(x:65,y:48,width:130,height:18)
        time.frame=NSRect(x:199,y:48,width:48,height:18)
        hint.frame=NSRect(x:263,y:48,width:116,height:18)
        line.frame=NSRect(x:17,y:17,width:310,height:21)
        expand.frame=NSRect(x:335,y:14,width:25,height:25);expand.autoresizingMask=[.minYMargin]
        expand.bezelStyle = .inline;expand.contentTintColor = .white;expand.target=self;expand.action=#selector(toggleExpanded);bg.addSubview(expand)
        dismiss.frame=NSRect(x:380,y:44,width:25,height:25);dismiss.autoresizingMask=[.minYMargin];dismiss.bezelStyle = .inline;dismiss.contentTintColor = .white;dismiss.font = .systemFont(ofSize:18);dismiss.target=self;dismiss.action=#selector(dismissTapped);dismiss.toolTip="收起浮窗";bg.addSubview(dismiss)
        copy.frame=NSRect(x:365,y:14,width:43,height:25);copy.bezelStyle = .inline
        copy.contentTintColor = .white;copy.autoresizingMask=[.minYMargin];copy.target=self;copy.action=#selector(copyTapped);copy.isEnabled=false;bg.addSubview(copy)
        full.isEditable=false;full.isSelectable=true;full.drawsBackground=false;full.textColor = .white;full.font = .systemFont(ofSize:14)
        full.textContainerInset=NSSize(width:4,height:6);full.autoresizingMask=[.width]
        scroll.frame=NSRect(x:14,y:16,width:392,height:132);scroll.hasVerticalScroller=true;scroll.drawsBackground=false;scroll.documentView=full;scroll.isHidden=true;bg.addSubview(scroll)
        retry.frame=NSRect(x:278,y:45,width:100,height:25);retry.bezelStyle = .inline;retry.contentTintColor = .white;retry.target=self;retry.action=#selector(retryTapped);retry.autoresizingMask=[.minYMargin];retry.isHidden=true;bg.addSubview(retry)
        place()
    }
    func place() {
        let area=(NSScreen.screens.first(where:{$0.frame.contains(NSEvent.mouseLocation)}) ?? NSScreen.main)?.visibleFrame ?? NSRect(x:0,y:0,width:1200,height:800)
        panel.setFrameOrigin(NSPoint(x:area.midX-panel.frame.width/2,y:area.minY+30))
    }
    func show(){hideWork?.cancel();hideWork=nil;place();panel.orderFrontRegardless()}
    func applyTheme(_ mode:CapsuleThemeMode,palette custom:CapsulePalette?=nil){
        let palette=custom ?? CapsulePalette.defaults[mode.rawValue] ?? .initial
        guard mode != theme || appliedPalette != palette,let background=panel.contentView as? CapsuleBackground else{return}
        theme=mode;appliedPalette=palette
        func rgb(_ hex:Int)->NSColor{NSColor(srgbRed:CGFloat((hex>>16)&255)/255,green:CGFloat((hex>>8)&255)/255,blue:CGFloat(hex&255)/255,alpha:1)}
        let ink=rgb(palette.foreground),muted=rgb(palette.muted)
        background.fill=mode == .initial ? NSColor(calibratedRed:0.137,green:0.153,blue:0.184,alpha:0.97) : rgb(palette.background)
        background.border=mode == .initial ? NSColor.white.withAlphaComponent(0.11) : rgb(palette.border);background.needsDisplay=true
        status.textColor=mode == .initial ? NSColor(calibratedWhite:0.86,alpha:1) : ink
        time.textColor=muted;hint.textColor=muted;line.textColor=ink;full.textColor=ink
        [dismiss,expand,copy,retry].forEach{$0.contentTintColor=ink}
        wave.color=rgb(palette.accent);wave.needsDisplay=true
        panel.appearance=NSAppearance(named:palette.dark ? .darkAqua : .aqua)
    }
    func preview(ifAllowed:@escaping()->Bool){
        previewUntil=Date().addingTimeInterval(4);let wasVisible=panel.isVisible;show()
        if !wasVisible{hide(after:4,ifAllowed:ifAllowed)}
    }
    func hide(after seconds:Double,ifAllowed:@escaping ()->Bool) {
        hideWork?.cancel()
        let work=DispatchWorkItem { [weak self] in if ifAllowed(){self?.panel.orderOut(nil)} }
        hideWork=work
        DispatchQueue.main.asyncAfter(deadline:.now()+seconds,execute:work)
    }
    func update(state:String,text:String,seconds:Double,recording:Bool,hotkey:Bool,retryable:Bool=false,keyLabel:String="右 Option") {
        if recording{previewUntil = .distantPast}
        if Date()<previewUntil {
            status.stringValue="配色预览";time.stringValue="00:00";hint.stringValue="悬浮窗配色预览";line.stringValue="说话时，文字会显示在这里…";full.string="说话时，文字会显示在这里…";retry.isHidden=true;hint.isHidden=false;copy.isEnabled=false;wave.active=false;return
        }
        if status.stringValue != state {status.stringValue=state}
        let clock=String(format:"%02d:%02d",Int(seconds)/60,Int(seconds)%60)
        if time.stringValue != clock {time.stringValue=clock}
        let shortcut=hotkey ? (recording ? keyLabel+" 结束" : keyLabel+" 开始") : "菜单栏开始 / 结束"
        if hint.stringValue != shortcut {hint.stringValue=shortcut;hint.toolTip=shortcut;hint.cell?.lineBreakMode = .byTruncatingMiddle}
        retry.isHidden = !retryable;hint.isHidden=retryable
        let dismissLabel=recording ? "取消本次录音，不保存或粘贴" : "收起浮窗，已有内容仍留在本机"
        dismiss.toolTip=dismissLabel;dismiss.setAccessibilityLabel(recording ? "取消本次录音" : "收起浮窗")
        let preview=text.isEmpty ? (recording ? "正在听，文字会显示在这里…" : "从菜单栏开始，或使用已设快捷键") : text.replacingOccurrences(of:"\n",with:" ")
        if line.stringValue != preview {line.stringValue=preview}
        if full.string != text {full.string=text;full.scrollToEndOfDocument(nil)}
        copy.isEnabled = !text.isEmpty
        if wave.active != recording {wave.active=recording}
    }
    func setLevel(_ rms:Double){wave.rms=rms}
    @objc private func toggleExpanded() {
        expanded.toggle();let old=panel.frame;let height:CGFloat=expanded ? 226 : 78
        panel.setFrame(NSRect(x:old.minX,y:old.minY,width:old.width,height:height),display:true,animate:false)
        scroll.isHidden = !expanded;line.isHidden=expanded;copy.frame.origin.y=expanded ? 165 : 14;expand.frame.origin.y=expanded ? 165 : 14
        expand.title=expanded ? "⌃" : "⌄"
    }
    @objc private func dismissTapped(){onDismiss?()}
    @objc private func copyTapped(){onCopy?()}
    @objc private func retryTapped(){onRetry?()}
}
