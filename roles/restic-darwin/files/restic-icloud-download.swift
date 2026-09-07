import Darwin
import Foundation

let paths = CommandLine.arguments.dropFirst()
guard !paths.isEmpty else {
    fputs("Usage: restic-icloud-download PATH...\n", stderr)
    exit(EX_USAGE)
}

let fileManager = FileManager.default
var failed = false

for path in paths {
    do {
        try fileManager.startDownloadingUbiquitousItem(
            at: URL(fileURLWithPath: path)
        )
    } catch {
        fputs("restic-icloud-download: \(path): \(error)\n", stderr)
        failed = true
    }
}

exit(failed ? EXIT_FAILURE : EXIT_SUCCESS)
