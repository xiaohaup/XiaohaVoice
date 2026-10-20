import Foundation

struct CapsuleThemeMode:RawRepresentable,Equatable {
    let rawValue:String
    init?(rawValue:String){guard rawValue.range(of:"^[a-z][a-z0-9-]{0,31}$",options:.regularExpression) != nil else{return nil};self.rawValue=rawValue}
    static let initial=CapsuleThemeMode(rawValue:"initial")!,follow=CapsuleThemeMode(rawValue:"follow")!,cocoa=CapsuleThemeMode(rawValue:"cocoa")!,mint=CapsuleThemeMode(rawValue:"mint")!,ink=CapsuleThemeMode(rawValue:"ink")!
}
struct CapsulePalette:Equatable {
    let background:Int,foreground:Int,muted:Int,border:Int,accent:Int,dark:Bool
    static let initial=CapsulePalette(background:0x23272f,foreground:0xffffff,muted:0xbfbfbf,border:0x3b3e45,accent:0x94dee8,dark:true)
    static let defaults:[String:CapsulePalette]=[
        "initial":initial,
        "cocoa":.init(background:0xf3efe9,foreground:0x40392f,muted:0x6f6252,border:0xd8cfc2,accent:0x785f45,dark:false),
        "mint":.init(background:0xf2f4ee,foreground:0x374638,muted:0x5e7055,border:0xd5decf,accent:0x55714b,dark:false),
        "ink":.init(background:0xeef2f5,foreground:0x34424c,muted:0x566b78,border:0xced9e1,accent:0x536f83,dark:false)]
    init(background:Int,foreground:Int,muted:Int,border:Int,accent:Int,dark:Bool){self.background=background;self.foreground=foreground;self.muted=muted;self.border=border;self.accent=accent;self.dark=dark}
    init?(_ object:[String:Any]){
        func color(_ key:String)->Int?{guard let raw=object[key] as? String,raw.range(of:"^#[0-9a-fA-F]{6}$",options:.regularExpression) != nil else{return nil};return Int(raw.dropFirst(),radix:16)}
        guard let background=color("background"),let foreground=color("foreground"),let muted=color("muted"),let border=color("border"),let accent=color("accent"),let dark=object["dark"] as? Bool else{return nil}
        self.init(background:background,foreground:foreground,muted:muted,border:border,accent:accent,dark:dark)
    }
}

final class CapsuleThemePreferences {
    let path:URL,workbenchPath:URL,catalogPath:URL?
    private var catalogVersion="",catalog=CapsulePalette.defaults
    private var cachedVersion="",cachedMode=CapsuleThemeMode.initial
    private var workbenchVersion="",workbenchTheme="cocoa"
    var previewTheme:String?
    init(directory:URL,catalogPath:URL?=nil){self.catalogPath=catalogPath;path=directory.appendingPathComponent("capsule-settings.json");workbenchPath=directory.appendingPathComponent("desktop/workbench.json")}
    private func version(_ url:URL)->String {
        guard let a=try? FileManager.default.attributesOfItem(atPath:url.path) else{return "missing"}
        return "\((a[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0):\(a[.size] ?? 0)"
    }
    var palettes:[String:CapsulePalette] {
        guard let file=catalogPath else{return catalog}
        let current=version(file)
        if current != catalogVersion {
            catalogVersion=current;catalog=CapsulePalette.defaults
            if let data=try? Data(contentsOf:file),data.count<=64_000,let rows=(try? JSONSerialization.jsonObject(with:data)) as? [String:[String:Any]] {
                for (id,row) in rows.prefix(32) where id != "follow" && id != "initial" {
                    if CapsuleThemeMode(rawValue:id) != nil,let palette=CapsulePalette(row){catalog[id]=palette}
                }
            }
        }
        return catalog
    }
    var palette:CapsulePalette {palettes[resolved.rawValue] ?? .initial}
    var mode:CapsuleThemeMode {
        let current=version(path)
        if current != cachedVersion {
            cachedVersion=current;cachedMode = .initial
            if let data=try? Data(contentsOf:path),let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],let raw=value["mode"] as? String,let mode=CapsuleThemeMode(rawValue:raw),raw=="follow" || palettes[raw] != nil{cachedMode=mode}
        }
        return cachedMode
    }
    func save(_ raw:String)throws {
        guard let mode=CapsuleThemeMode(rawValue:raw),raw=="follow" || palettes[raw] != nil else{throw NSError(domain:"请选择可用的悬浮窗配色",code:1)}
        let data=try JSONSerialization.data(withJSONObject:["mode":mode.rawValue])
        try FileManager.default.createDirectory(at:path.deletingLastPathComponent(),withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        try data.write(to:path,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        cachedVersion=""
    }
    func preview(_ raw:String)throws {
        guard ["cocoa","mint","ink"].contains(raw) else{throw NSError(domain:"主题配色无效",code:1)}
        previewTheme=raw
    }
    var resolved:CapsuleThemeMode {
        let selected=mode
        guard selected == .follow else{return selected}
        if let preview=previewTheme{return CapsuleThemeMode(rawValue:preview) ?? .cocoa}
        let current=version(workbenchPath)
        if current != workbenchVersion {
            workbenchVersion=current;workbenchTheme="cocoa"
            if let data=try? Data(contentsOf:workbenchPath),let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],let theme=value["theme"] as? String,["cocoa","mint","ink"].contains(theme){workbenchTheme=theme}
        }
        return CapsuleThemeMode(rawValue:workbenchTheme) ?? .cocoa
    }
}
