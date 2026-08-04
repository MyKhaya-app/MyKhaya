import { Platform } from "react-native";
import { appVersion } from "../config/appVersion";

/**
 * Display/diagnostic metadata only - shown in a future "your devices" list
 * via Session.user_agent. The server never trusts these for authentication,
 * authorisation or rate limiting (see ADR 0010).
 */
export function clientHeaders(): Record<string, string> {
  return {
    "X-MyKhaya-Client": "mobile",
    "X-MyKhaya-Platform": Platform.OS,
    "X-MyKhaya-App-Version": appVersion,
  };
}
