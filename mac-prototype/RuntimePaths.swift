import Foundation

enum RuntimePaths {
    static var toolkit:URL? {
        let parent=Bundle.main.bundleURL.resolvingSymlinksInPath().deletingLastPathComponent()
        guard let d=try? Data(contentsOf:parent.appendingPathComponent("toolkit.json")),let v=(try? JSONSerialization.jsonObject(with:d)) as? [String:Any],v["format"] as? Int==1 else{return nil}
        return parent
    }
    static var legacyRoot:URL{URL(fileURLWithPath:Bundle.main.infoDictionary!["PrototypeRoot"] as! String)}
    static var data:URL{toolkit?.appendingPathComponent("Data") ?? legacyRoot.appendingPathComponent("private")}
    static var engine:URL{toolkit?.appendingPathComponent("Components/engine") ?? URL(fileURLWithPath:Bundle.main.infoDictionary!["BridgeRoot"] as! String)}
    static var workbench:URL{toolkit?.appendingPathComponent("Components/workbench") ?? legacyRoot.deletingLastPathComponent().appendingPathComponent("sync-suite")}
    static var companion:URL{toolkit != nil ? data.appendingPathComponent("desktop") : workbench.appendingPathComponent("private/desktop")}
    static var executable:URL?{toolkit?.appendingPathComponent("Runtime/xiaoha-runtime/xiaoha-runtime")}
    static var environment:[String:String]{
        var e=ProcessInfo.processInfo.environment
        e["XH_VOICE_DATA"]=data.path;e["XH_VOICE_ENGINE"]=engine.path;e["XH_VOICE_WORKBENCH"]=workbench.path
        e["XH_VOICE_IDENTITY"]=(toolkit != nil ? data.appendingPathComponent("recognition") : engine.appendingPathComponent("private")).path
        return e
    }
}
