import Foundation
import LocalAuthentication

// Touch-ID-gated read of a generic-password Keychain item.
//
// Items with a biometric access control (kSecAccessControlBiometryCurrentSet)
// need an Apple-Developer-signed binary with Keychain entitlements, which a
// helper compiled on the fly does not have. So the responsibility is split:
//   1. LAContext.evaluatePolicy fires Touch ID (no entitlements needed).
//   2. Only once that succeeds, /usr/bin/security reads the password.
//
// For step 2 to be silent, the item must trust /usr/bin/security. That is the
// case when `security add-generic-password` created it (envref's
// `op save-password` does), or when "Always Allow" was clicked once.
//
// Usage: envref-touchid get <service> <account> [reason]
//   exit 0 → password on stdout
//   exit 2 → user cancelled / Touch ID failed
//   exit 3 → item not found
//   exit 1 → other error (message on stderr)

func die(_ msg: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(code)
}

let args = CommandLine.arguments
guard args.count >= 4, args[1] == "get" else {
    die("usage: \(args[0]) get <service> <account> [reason]")
}
let service = args[2]
let account = args[3]
let reason = args.count >= 5 && !args[4].isEmpty ? args[4] : "read a secret from the keychain"

let context = LAContext()
var laError: NSError?
guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &laError) else {
    die("biometrics unavailable: \(laError?.localizedDescription ?? "unknown")")
}

let sem = DispatchSemaphore(value: 0)
var authOK = false
context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason) { success, _ in
    authOK = success
    sem.signal()
}
sem.wait()
guard authOK else { exit(2) }

let task = Process()
task.launchPath = "/usr/bin/security"
var arguments = ["find-generic-password", "-w", "-s", service]
if !account.isEmpty {
    arguments += ["-a", account]
}
task.arguments = arguments
let outPipe = Pipe()
let errPipe = Pipe()
task.standardOutput = outPipe
task.standardError = errPipe
do {
    try task.run()
} catch {
    die("failed to launch /usr/bin/security: \(error)")
}
task.waitUntilExit()

if task.terminationStatus == 44 {  // errSecItemNotFound
    exit(3)
}
if task.terminationStatus != 0 {
    let errText = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    die("security returned \(task.terminationStatus): \(errText)")
}

FileHandle.standardOutput.write(outPipe.fileHandleForReading.readDataToEndOfFile())
