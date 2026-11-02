import AppKit

struct PanelShortcut:Codable {
    var enabled:Bool=false
    var keyCode:Int=56
    var modifiers:UInt64=0
    var label:String="未启用"
    var mouseButton:Int?=nil
    var mode:String?=nil
    var valid:Bool {
        if !enabled{return true}
        let value=VoiceShortcut(keyCode:keyCode,modifiers:modifiers,label:label,mouseButton:mouseButton)
        return value.valid && (mode == nil || mode == "single" || (mode == "double" && [56,60,59,62,58,61,54,55].contains(keyCode)))
    }
    func conflicts(_ voice:VoiceShortcut)->Bool {
        if !enabled{return false}
        if let mouse=mouseButton{return voice.mouseButton==mouse}
        return keyCode==voice.keyCode && modifiers==voice.modifiers && voice.mouseButton==nil
    }
    var signature:String {"\(keyCode)|\(modifiers)|\(mouseButton ?? -1)"}
}
final class PanelGesture {
    var config:PanelShortcut
    private var armed=false,used=false,lastRelease=0.0,pressedAt=0.0
    init(_ config:PanelShortcut){self.config=config}
    func handle(_ type:CGEventType,_ event:CGEvent)->(fire:Bool,consume:Bool){
        guard config.enabled else{return (false,false)}
        let key=Int(event.getIntegerValueField(.keyboardEventKeycode)),button=Int(event.getIntegerValueField(.mouseEventButtonNumber)),now=Date.timeIntervalSinceReferenceDate
        if let mouse=config.mouseButton {
            if type == .otherMouseDown && button==mouse{armed=true;used=false;return(false,true)}
            if type == .otherMouseUp && button==mouse{let result=armed && !used;armed=false;return(result,true)}
            if type == .keyDown || type == .leftMouseDown || type == .rightMouseDown{used=true};return(false,false)
        }
        if VoiceShortcut.modifierKeys.contains(config.keyCode){
            let masks:[Int:UInt64]=[54:0x10,55:0x08,56:0x02,58:0x20,59:0x01,60:0x04,61:0x40,62:0x2000]
            let expected:[Int:UInt64]=[54:0x100000,55:0x100000,56:0x20000,60:0x20000,58:0x80000,61:0x80000,59:0x40000,62:0x40000]
            // Always respect the physical side, including double taps.
            let matches=key==config.keyCode
            if type == .flagsChanged && matches {
                let down=event.flags.rawValue & (masks[key] ?? 0) != 0
                if down{armed=true;used=event.flags.rawValue & VoiceShortcut.flagMask != expected[key];pressedAt=now}
                else{let tap=armed && !used && now-pressedAt<0.65;armed=false
                    if tap{if config.mode=="double"{if lastRelease>0 && now-lastRelease<0.4{lastRelease=0;return(true,false)};lastRelease=now}else{return(true,false)}}else{lastRelease=0}}
            } else if type == .keyDown || type == .flagsChanged || type == .leftMouseDown || type == .rightMouseDown || type == .otherMouseDown {used=true;lastRelease=0}
            return(false,false)
        }
        if type == .keyDown {
            if key==config.keyCode && event.flags.rawValue & VoiceShortcut.flagMask==config.modifiers && event.getIntegerValueField(.keyboardEventAutorepeat)==0{armed=true;used=false;return(false,true)}
            if key != config.keyCode{used=true}
        } else if type == .keyUp && key==config.keyCode && armed {let result = !used;armed=false;return(result,true)}
        return(false,false)
    }
}
