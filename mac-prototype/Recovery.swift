import Foundation

struct RecoveryRecord:Codable {
    let id:UUID
    let createdAt:Date
    let text:String
    let seconds:Double
    var application:String?
}

// Only failed/unfinished sessions are archived. Normal successful recordings never go to disk.
final class RecoveryArchive {
    let directory:URL
    init(directory:URL){self.directory=directory}
    func save(_ session:VoiceSession) throws {
        guard !session.complete,!session.pcm.isEmpty else{return}
        let folder=directory.appendingPathComponent(session.id.uuidString)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        try FileManager.default.setAttributes([.posixPermissions:0o700],ofItemAtPath:directory.path)
        try FileManager.default.setAttributes([.posixPermissions:0o700],ofItemAtPath:folder.path)
        let pcm=folder.appendingPathComponent("audio.pcm"),info=folder.appendingPathComponent("record.json")
        try session.pcm.write(to:pcm,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:pcm.path)
        let row=RecoveryRecord(id:session.id,createdAt:session.createdAt,text:session.text,seconds:session.seconds,application:session.applicationName)
        try JSONEncoder().encode(row).write(to:info,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:info.path)
    }
    func load(excluding completed:Set<UUID>) throws ->[VoiceSession] {
        guard FileManager.default.fileExists(atPath:directory.path) else{return []}
        var result=[VoiceSession]()
        for folder in try FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil) {
            guard let id=UUID(uuidString:folder.lastPathComponent),!completed.contains(id) else{continue}
            let info=folder.appendingPathComponent("record.json"),audio=folder.appendingPathComponent("audio.pcm")
            let row=try JSONDecoder().decode(RecoveryRecord.self,from:Data(contentsOf:info))
            guard row.id==id else{throw NSError(domain:"恢复录音身份不匹配",code:1)}
            let attrs=try FileManager.default.attributesOfItem(atPath:audio.path)
            guard let size=attrs[.size] as? NSNumber,size.intValue<=512_000_000,size.intValue>0,size.intValue%2==0 else{throw NSError(domain:"恢复录音大小无效",code:2)}
            let session=VoiceSession(id:row.id,createdAt:row.createdAt)
            session.append(try Data(contentsOf:audio));session.requestStop();session.captureDidEnd()
            session.text=row.text;session.applicationName=row.application;session.restored=true
            session.connectionFailed("上次识别未完成，音频已保存在本机，可重试。")
            result.append(session)
        }
        return result.sorted{$0.createdAt>$1.createdAt}
    }
    func discard(_ id:UUID) throws {
        let folder=directory.appendingPathComponent(id.uuidString)
        guard FileManager.default.fileExists(atPath:folder.path) else{return}
        try FileManager.default.trashItem(at:folder,resultingItemURL:nil)
    }
}
