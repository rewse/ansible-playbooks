import Cocoa

// Posts macOS system-defined media key events (NSSystemDefined / subtype 8).
//
// Why this exists: macOS 27 does not apply the "F1-F12 to media key" conversion to
// synthetic key events posted by software, so a device driver that emits a plain F10
// keycode no longer triggers mute. Posting the media key usage directly still works.

let keyCodes: [String: Int32] = [
    "brightness-down": 3,   // NX_KEYTYPE_BRIGHTNESS_DOWN
    "brightness-up": 2,     // NX_KEYTYPE_BRIGHTNESS_UP
    "fast-forward": 19,     // NX_KEYTYPE_FAST
    "keyboard-light-down": 22, // NX_KEYTYPE_ILLUMINATION_DOWN
    "keyboard-light-up": 21,   // NX_KEYTYPE_ILLUMINATION_UP
    "mute": 7,              // NX_KEYTYPE_MUTE
    "next": 17,             // NX_KEYTYPE_NEXT
    "play-pause": 16,       // NX_KEYTYPE_PLAY
    "previous": 18,         // NX_KEYTYPE_PREVIOUS
    "rewind": 20,           // NX_KEYTYPE_REWIND
    "volume-down": 1,       // NX_KEYTYPE_SOUND_DOWN
    "volume-up": 0,         // NX_KEYTYPE_SOUND_UP
]

func post(_ code: Int32) {
    for state in [0xa, 0xb] { // 0xa: key down, 0xb: key up
        let data1 = Int((code << 16) | Int32(state << 8))
        guard let event = NSEvent.otherEvent(with: .systemDefined,
                                            location: .zero,
                                            modifierFlags: NSEvent.ModifierFlags(rawValue: UInt(state << 8)),
                                            timestamp: 0,
                                            windowNumber: 0,
                                            context: nil,
                                            subtype: 8,
                                            data1: data1,
                                            data2: -1) else {
            FileHandle.standardError.write("mediakey: failed to create event\n".data(using: .utf8)!)
            exit(1)
        }
        event.cgEvent?.post(tap: .cghidEventTap)
        usleep(30_000)
    }
}

let arguments = CommandLine.arguments
guard arguments.count > 1, let code = keyCodes[arguments[1]] else {
    let names = keyCodes.keys.sorted().joined(separator: "\n  ")
    print("usage: mediakey <key>\n\nkeys:\n  \(names)")
    exit(arguments.count > 1 ? 1 : 0)
}

// Optional repeat count, useful for volume and brightness steps.
let repeatCount = arguments.count > 2 ? max(1, Int(arguments[2]) ?? 1) : 1
for _ in 0..<repeatCount {
    post(code)
}
