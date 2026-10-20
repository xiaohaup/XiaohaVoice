import AppKit

// Finder metadata only. Does not replace signed resources or executable code.
guard CommandLine.arguments.count==3,let image=NSImage(contentsOfFile:CommandLine.arguments[1]) else {
    fputs("Expected an icon image and existing file path\n",stderr);exit(2)
}
guard NSWorkspace.shared.setIcon(image,forFile:CommandLine.arguments[2],options:[]) else {
    fputs("Unable to set file icon\n",stderr);exit(1)
}
print("File icon updated")
