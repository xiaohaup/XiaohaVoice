import AppKit

final class WorkbenchDragStrip:NSView {
    init() {
        super.init(frame:.zero)
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityLabel("窗口拖动区域")
        setAccessibilityHelp("按住这里拖动窗口")
        setAccessibilityValue("可拖动")
    }
    required init?(coder:NSCoder){fatalError("init(coder:) is not supported")}
    override func acceptsFirstMouse(for event:NSEvent?) -> Bool {true}
    override func mouseDown(with event:NSEvent) {
        guard let window=window else{return}
        let original=window.frame.origin
        window.performDrag(with:event)
        if window.frame.origin != original {setAccessibilityValue("窗口已移动")}
    }
}

// Keep the drag hit area outside WebKit's own scrolling/flipped view hierarchy.
final class WorkbenchChrome:NSView {
    let content:NSView
    let dragStrip=WorkbenchDragStrip()
    private var initialOrigin:NSPoint?
    func trackWindowMovement(){initialOrigin=window?.frame.origin}
    func windowMoved(){if let initialOrigin=initialOrigin,window?.frame.origin != initialOrigin {dragStrip.setAccessibilityValue("窗口已移动")}}
    override var isFlipped:Bool {true}
    init(content:NSView) {
        self.content=content
        super.init(frame:.zero)
        addSubview(content)
        addSubview(dragStrip,positioned:.above,relativeTo:content)
        layoutParts()
    }
    required init?(coder:NSCoder){fatalError("init(coder:) is not supported")}
    override func setFrameSize(_ newSize:NSSize) {
        super.setFrameSize(newSize)
        layoutParts()
    }
    override func layout(){super.layout();layoutParts()}
    private func layoutParts() {
        content.frame=bounds
        dragStrip.frame=NSRect(x:84,y:0,width:max(0,bounds.width-84),height:min(24,bounds.height))
    }
}
