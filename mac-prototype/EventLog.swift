import Foundation

enum EventLog {
    static func record(_ event:String,phase:String,seconds:Double?=nil){
        guard ["capture","recognition","delivery","backup","restore"].contains(event) else{return}
        let settings=RuntimePaths.data.appendingPathComponent("runtime-settings.json")
        if let data=try? Data(contentsOf:settings),let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],value["logs_enabled"] as? Bool==false{return}
        let folder=RuntimePaths.data.appendingPathComponent("logs")
        do {
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
            let path=folder.appendingPathComponent("runtime-native-\(ProcessInfo.processInfo.processIdentifier).jsonl")
            if let size=(try? FileManager.default.attributesOfItem(atPath:path.path)[.size]) as? NSNumber,size.intValue>262144{return}
            var value:[String:Any]=["time":ISO8601DateFormatter().string(from:Date()),"event":event,"phase":phase]
            if let seconds=seconds,seconds.isFinite,seconds>=0{value["seconds"]=seconds}
            let line=try JSONSerialization.data(withJSONObject:value)+Data([10])
            if !FileManager.default.fileExists(atPath:path.path){FileManager.default.createFile(atPath:path.path,contents:nil,attributes:[.posixPermissions:0o600])}
            let handle=try FileHandle(forWritingTo:path);defer{try? handle.close()};try handle.seekToEnd();try handle.write(contentsOf:line)
        } catch {}
    }
}
