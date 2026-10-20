import AppKit
let directory=URL(fileURLWithPath:CommandLine.arguments[1])
try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
for points in [16,32,128,256,512] {
    for scale in [1,2] {
        let size=points*scale,c=CGFloat(size)
        let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
        let transform=NSAffineTransform();transform.scale(by:c/64);transform.translateX(by:0,yBy:64);transform.scaleX(by:1,yBy:-1);transform.concat()
        NSColor(calibratedRed:232/255,green:223/255,blue:210/255,alpha:1).setFill()
        NSBezierPath(roundedRect:NSRect(x:3,y:3,width:58,height:58),xRadius:16.3125,yRadius:16.3125).fill()
        let inset=NSAffineTransform();inset.translateX(by:3,yBy:3);inset.scale(by:58/64);inset.concat()
        let ink=NSColor(calibratedRed:120/255,green:95/255,blue:69/255,alpha:1);ink.setStroke();ink.setFill()
        let small=NSBezierPath();small.lineWidth=5;small.lineCapStyle = .round
        small.move(to:NSPoint(x:31,y:12));small.line(to:NSPoint(x:31,y:48));small.curve(to:NSPoint(x:24,y:52),controlPoint1:NSPoint(x:31,y:52.6667),controlPoint2:NSPoint(x:28.6667,y:54))
        small.move(to:NSPoint(x:19,y:31));small.line(to:NSPoint(x:12,y:45));small.move(to:NSPoint(x:44,y:31));small.line(to:NSPoint(x:52,y:45));small.stroke()
        NSBezierPath(roundedRect:NSRect(x:25,y:10,width:12,height:24),xRadius:6,yRadius:6).fill()
        let mic=NSBezierPath();mic.lineWidth=3;mic.lineCapStyle = .round
        mic.move(to:NSPoint(x:21,y:26));mic.line(to:NSPoint(x:21,y:29));mic.curve(to:NSPoint(x:31,y:42),controlPoint1:NSPoint(x:21,y:37.6667),controlPoint2:NSPoint(x:24.3333,y:42));mic.curve(to:NSPoint(x:41,y:29),controlPoint1:NSPoint(x:37.6667,y:42),controlPoint2:NSPoint(x:41,y:37.6667));mic.line(to:NSPoint(x:41,y:26));mic.stroke()
        NSGraphicsContext.restoreGraphicsState()
        let suffix=scale==2 ? "@2x" : ""
        try rep.representation(using:.png,properties:[:])!.write(to:directory.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
    }
}
