import Foundation

final class SpeechBridge {
    private let process=Process()
    private let input=Pipe(), output=Pipe()
    private let writes=DispatchQueue(label:"voice.bridge.write")
    private var buffer=Data()
    var onEvent:(([String:Any])->Void)?
    var onExit:((Int32)->Void)?
    private(set) var running=false
    func start(root:URL) throws {
        process.executableURL=RuntimePaths.executable ?? root.appendingPathComponent(".venv/bin/python")
        process.arguments=RuntimePaths.executable != nil ? ["bridge"] : [root.appendingPathComponent("channel_probe.py").path,"bridge"]
        process.environment=RuntimePaths.environment
        process.standardInput=input;process.standardOutput=output;process.standardError=FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler={ [weak self] handle in
            let data=handle.availableData
            guard !data.isEmpty else {handle.readabilityHandler=nil;return}
            DispatchQueue.main.async {self?.parse(data)}
        }
        process.terminationHandler={ [weak self] p in DispatchQueue.main.async {
            guard let self=self else{return};self.running=false;self.onExit?(p.terminationStatus)
        }}
        try process.run();running=true
    }
    private func parse(_ data:Data) {
        buffer.append(data)
        while let newline=buffer.firstIndex(of:10) {
            let line=buffer.prefix(upTo:newline);buffer.removeSubrange(...newline)
            if let item=(try? JSONSerialization.jsonObject(with:line)) as? [String:Any] {onEvent?(item)}
        }
    }
    private func send(_ item:[String:Any]) {
        guard let data=try? JSONSerialization.data(withJSONObject:item) else{return}
        let handle=input.fileHandleForWriting
        writes.async {do {try handle.write(contentsOf:data+Data([10]))} catch {}}
    }
    func audio(_ data:Data, replay:Bool=false) {
        guard !data.isEmpty else{return}
        // Keep memory/pipe chunks bounded even after a connection was preparing.
        for offset in stride(from:0,to:data.count,by:3200) {
            let chunk=data.subdata(in:offset..<min(data.count,offset+3200))
            send(["event":"audio","pcm":chunk.base64EncodedString(),"replay":replay])
        }
    }
    func finish(){send(["event":"stop"])}
    func cancel(){if running{process.terminate()}}
    deinit {cancel()}
}
