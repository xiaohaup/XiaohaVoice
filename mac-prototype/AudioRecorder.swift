import AVFoundation
import CoreMedia

final class AudioRecorder: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    private let queue = DispatchQueue(label:"voice.capture")
    private let work = DispatchQueue(label:"voice.capture.lifecycle")
    private var session: AVCaptureSession?
    private var formatChecked = false
    var onAudio: ((Data, Double) -> Void)?
    var onError: ((String) -> Void)?
    private(set) var deviceName = "Mac 内建麦克风"
    func start() throws {
        guard session == nil else { return }
        let devices = AVCaptureDevice.DiscoverySession(deviceTypes:[.microphone],mediaType:.audio,position:.unspecified).devices
        guard let device = devices.first(where: { $0.uniqueID.lowercased().contains("builtinmicrophone") || $0.localizedName.contains("MacBook") }) else { throw NSError(domain:"未找到 Mac 内建麦克风",code:1) }
        deviceName = device.localizedName
        let capture = AVCaptureSession(), output = AVCaptureAudioDataOutput()
        output.audioSettings=[AVFormatIDKey:kAudioFormatLinearPCM,AVSampleRateKey:16000,AVNumberOfChannelsKey:1,AVLinearPCMBitDepthKey:16,AVLinearPCMIsFloatKey:false,AVLinearPCMIsBigEndianKey:false,AVLinearPCMIsNonInterleaved:false]
        output.setSampleBufferDelegate(self,queue:queue)
        let input = try AVCaptureDeviceInput(device:device)
        capture.beginConfiguration()
        guard capture.canAddInput(input),capture.canAddOutput(output) else { throw NSError(domain:"无法启动内建麦克风",code:2) }
        capture.addInput(input);capture.addOutput(output);capture.commitConfiguration()
        formatChecked=false;session=capture
        work.async { capture.startRunning() }
    }
    func stop(completion:@escaping () -> Void) {
        let capture=session;session=nil
        work.async {
            capture?.stopRunning()
            self.queue.async { DispatchQueue.main.async { completion() } }
        }
    }
    func captureOutput(_ output:AVCaptureOutput,didOutput sampleBuffer:CMSampleBuffer,from connection:AVCaptureConnection) {
        guard let format=CMSampleBufferGetFormatDescription(sampleBuffer),let stream=CMAudioFormatDescriptionGetStreamBasicDescription(format) else{return}
        let f=stream.pointee
        if !formatChecked {
            guard f.mSampleRate==16000,f.mChannelsPerFrame==1,f.mBitsPerChannel==16,(f.mFormatFlags & kAudioFormatFlagIsFloat)==0 else {
                DispatchQueue.main.async {self.onError?("麦克风格式不匹配，无法继续采集。")};return
            }
            formatChecked=true
        }
        guard let block=CMSampleBufferGetDataBuffer(sampleBuffer) else{return}
        let count=CMBlockBufferGetDataLength(block)
        guard count>0 else{return}
        var pcm=Data(count:count)
        let code=pcm.withUnsafeMutableBytes { CMBlockBufferCopyDataBytes(block,atOffset:0,dataLength:count,destination:$0.baseAddress!) }
        guard code==kCMBlockBufferNoErr else{return}
        var energy=0.0
        pcm.withUnsafeBytes {for x in $0.bindMemory(to:Int16.self) {let v=Double(x)/32768;energy+=v*v}}
        let rms=sqrt(energy/Double(count/2))
        DispatchQueue.main.async {self.onAudio?(pcm,rms)}
    }
}
