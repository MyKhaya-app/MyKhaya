import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
export default function Layout() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: "#7D8F7A" },
          headerTintColor: "#fff",
          contentStyle: { backgroundColor: "#FAF7F1" },
        }}
      />
    </>
  );
}
