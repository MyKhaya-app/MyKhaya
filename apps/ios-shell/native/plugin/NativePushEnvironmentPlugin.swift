import Capacitor
import Foundation
import Security

/// Exposes the signed `aps-environment` entitlement to the web registration
/// layer. The value comes from the installed binary, never from its API host.
@objc(NativePushEnvironmentPlugin)
public class NativePushEnvironmentPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativePushEnvironmentPlugin"
    public let jsName = "NativePushEnvironment"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getEnvironment", returnType: CAPPluginReturnPromise),
    ]

    @objc func getEnvironment(_ call: CAPPluginCall) {
        guard let task = SecTaskCreateFromSelf(nil),
              let value = SecTaskCopyValueForEntitlement(task, "aps-environment" as CFString, nil) as? String else {
            call.reject("Signed APNs environment entitlement is missing")
            return
        }
        switch value {
        case "development": call.resolve(["environment": "sandbox"])
        case "production": call.resolve(["environment": "production"])
        default: call.reject("Signed APNs environment entitlement is invalid")
        }
    }
}
