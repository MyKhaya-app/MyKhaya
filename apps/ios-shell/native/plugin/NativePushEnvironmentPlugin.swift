import Capacitor
import Foundation

/// Exposes the APNs environment selected by the signed app build configuration
/// to the web registration layer. The same build setting expands into the
/// app's aps-environment entitlement and this private Info.plist key; it is
/// never inferred from the API host.
@objc(NativePushEnvironmentPlugin)
public class NativePushEnvironmentPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativePushEnvironmentPlugin"
    public let jsName = "NativePushEnvironment"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getEnvironment", returnType: CAPPluginReturnPromise),
    ]

    @objc func getEnvironment(_ call: CAPPluginCall) {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "MyKhayaAPNsEnvironment") as? String else {
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
