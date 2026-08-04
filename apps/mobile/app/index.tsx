import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { appVersion } from "../src/config/appVersion";
import { checkApiHealth, type ApiHealthResult } from "../src/api/health";
import { authorizedFetch } from "../src/api/authorizedFetch";
import { login, logout, type SignedInUser } from "../src/auth/authClient";

function connectionCopy(result: ApiHealthResult | null): { bold: string; muted: string } {
  if (result === null) {
    return { bold: "Checking connection…", muted: "Looking for the MyKhaya API" };
  }
  if (result.status === "connected") {
    return { bold: "Connected", muted: "The MyKhaya API is reachable" };
  }
  return { bold: "Not connected yet", muted: result.message };
}

async function fetchSignedInUser(): Promise<SignedInUser | null> {
  const response = await authorizedFetch("/api/v1/users/me");
  if (!response.ok) return null;
  const data = (await response.json()) as {
    id: string;
    email: string;
    display_name: string;
    email_verified: boolean;
  };
  return {
    id: data.id,
    email: data.email,
    displayName: data.display_name,
    emailVerified: data.email_verified,
  };
}

export default function Home() {
  const [health, setHealth] = useState<ApiHealthResult | null>(null);
  const [user, setUser] = useState<SignedInUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signInError, setSignInError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void checkApiHealth().then((result) => {
      if (!cancelled) setHealth(result);
    });
    void fetchSignedInUser()
      .then((result) => {
        if (!cancelled) setUser(result);
      })
      .finally(() => {
        if (!cancelled) setCheckingSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const connection = connectionCopy(health);

  const handleSignIn = async (): Promise<void> => {
    setSignInError(null);
    setSigningIn(true);
    try {
      const signedIn = await login(email.trim(), password);
      setUser(signedIn);
      setPassword("");
    } catch (error) {
      setSignInError((error as Error).message);
    } finally {
      setSigningIn(false);
    }
  };

  const handleSignOut = async (): Promise<void> => {
    await logout();
    setUser(null);
  };

  return (
    <SafeAreaView style={styles.page}>
      <View style={styles.hero}>
        <Text style={styles.time}>Your family’s digital home</Text>
        <Text style={styles.title}>
          {user ? `Good evening, ${user.displayName.split(" ")[0]} 👋` : "Good evening 👋"}
        </Text>
        <Text style={styles.copy}>
          The native MyKhaya experience is taking shape.
        </Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.heading}>Today</Text>
        <View style={styles.row}>
          <Text style={styles.icon}>✓</Text>
          <View>
            <Text style={styles.bold}>A calm start</Text>
            <Text style={styles.muted}>Your shared plans will appear here</Text>
          </View>
        </View>
        <View style={styles.row}>
          <Text style={styles.icon}>♙</Text>
          <View>
            <Text style={styles.bold}>People stay close</Text>
            <Text style={styles.muted}>Private to the Homes you join</Text>
          </View>
        </View>
        <View style={styles.row}>
          <Text style={styles.icon}>⇄</Text>
          <View>
            <Text style={styles.bold}>{connection.bold}</Text>
            <Text style={styles.muted}>{connection.muted}</Text>
          </View>
        </View>
      </View>

      {checkingSession ? (
        <ActivityIndicator style={styles.sessionSpinner} color="#566B58" />
      ) : user ? (
        <View style={styles.card}>
          <Text style={styles.heading}>Signed in</Text>
          <Text style={styles.muted}>{user.email}</Text>
          <TouchableOpacity
            accessibilityRole="button"
            style={[styles.button, styles.secondaryButton]}
            onPress={() => void handleSignOut()}
          >
            <Text style={styles.buttonText}>Sign out</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.heading}>Sign in</Text>
          <TextInput
            accessibilityLabel="Email address"
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            placeholder="Email address"
            style={styles.input}
            value={email}
            onChangeText={setEmail}
          />
          <TextInput
            accessibilityLabel="Password"
            autoComplete="password"
            placeholder="Password"
            secureTextEntry
            style={styles.input}
            value={password}
            onChangeText={setPassword}
          />
          {signInError ? <Text style={styles.error}>{signInError}</Text> : null}
          <TouchableOpacity
            accessibilityRole="button"
            disabled={signingIn}
            style={styles.button}
            onPress={() => void handleSignIn()}
          >
            {signingIn ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.buttonText}>Sign in</Text>
            )}
          </TouchableOpacity>
        </View>
      )}
      <Text style={styles.note}>
        Credentials will be stored only in platform secure storage.
      </Text>
      <Text style={styles.version}>MyKhaya {appVersion}</Text>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  page: { backgroundColor: "#FAF7F1", flex: 1, padding: 18 },
  hero: {
    backgroundColor: "#6B806C",
    borderRadius: 24,
    padding: 24,
    marginTop: 16,
  },
  time: { color: "#E8EFE7", fontSize: 13 },
  title: { color: "#fff", fontSize: 28, fontWeight: "700", marginTop: 28 },
  copy: { color: "#F6F2EB", lineHeight: 21, marginTop: 8 },
  card: {
    backgroundColor: "#FFFEFB",
    borderRadius: 18,
    marginTop: 18,
    padding: 18,
    shadowColor: "#1F2933",
    shadowOpacity: 0.08,
    shadowRadius: 18,
  },
  heading: {
    color: "#1F2933",
    fontSize: 18,
    fontWeight: "700",
    marginBottom: 8,
  },
  row: {
    alignItems: "center",
    borderTopColor: "#EEE8DF",
    borderTopWidth: 1,
    display: "flex",
    flexDirection: "row",
    gap: 12,
    paddingVertical: 16,
  },
  icon: {
    backgroundColor: "#E07A5F",
    borderRadius: 9,
    color: "#fff",
    fontSize: 18,
    overflow: "hidden",
    padding: 9,
  },
  bold: { color: "#1F2933", fontWeight: "700" },
  muted: { color: "#62706F", fontSize: 12, marginTop: 3 },
  input: {
    borderColor: "#EEE8DF",
    borderRadius: 12,
    borderWidth: 1,
    fontSize: 15,
    marginTop: 10,
    minHeight: 44,
    paddingHorizontal: 14,
  },
  error: {
    color: "#A33E2B",
    fontSize: 13,
    marginTop: 10,
  },
  button: {
    alignItems: "center",
    backgroundColor: "#566B58",
    borderRadius: 12,
    marginTop: 22,
    minHeight: 44,
    justifyContent: "center",
    padding: 15,
  },
  secondaryButton: {
    backgroundColor: "#8A7A66",
  },
  buttonText: { color: "#fff", fontWeight: "700" },
  sessionSpinner: {
    marginTop: 18,
  },
  note: {
    color: "#62706F",
    fontSize: 12,
    lineHeight: 18,
    padding: 20,
    textAlign: "center",
  },
  version: {
    color: "#62706F",
    fontSize: 11,
    textAlign: "center",
  },
});
