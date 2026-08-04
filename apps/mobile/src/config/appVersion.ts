import Constants from "expo-constants";

export const appVersion =
  (Constants.expoConfig?.extra?.mykhayaVersion as string | undefined) ?? "unknown";
