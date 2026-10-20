import Foundation

struct VoiceRecord: Codable {
    let id: UUID
    let createdAt: Date
    let text: String
    let seconds: Double
    var application: String? = nil
    var characters: Int { text.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.count }
}

final class HistoryStore {
    private let path: URL
    private(set) var records: [VoiceRecord] = []
    init(directory: URL) throws {
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        try FileManager.default.setAttributes([.posixPermissions:0o700],ofItemAtPath:directory.path)
        path=directory.appendingPathComponent("history.json")
        if FileManager.default.fileExists(atPath:path.path) {
            records=try JSONDecoder().decode([VoiceRecord].self,from:Data(contentsOf:path))
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        }
    }
    func append(_ record:VoiceRecord) throws {
        guard !record.text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else{return}
        guard !records.contains(where:{$0.id==record.id}) else{return}
        let next=[record]+records
        let data=try JSONEncoder().encode(next)
        try data.write(to:path,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        records=next
    }
    var characters:Int {records.reduce(0){$0+$1.characters}}
    var seconds:Double {records.reduce(0){$0+$1.seconds}}
}
