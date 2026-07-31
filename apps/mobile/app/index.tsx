import {
  SafeAreaView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
export default function Home() {
  return (
    <SafeAreaView style={styles.page}>
      <View style={styles.hero}>
        <Text style={styles.time}>Your family’s digital home</Text>
        <Text style={styles.title}>Good evening 👋</Text>
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
      </View>
      <TouchableOpacity accessibilityRole="button" style={styles.button}>
        <Text style={styles.buttonText}>Sign in</Text>
      </TouchableOpacity>
      <Text style={styles.note}>
        Credentials will be stored only in platform secure storage.
      </Text>
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
  button: {
    alignItems: "center",
    backgroundColor: "#566B58",
    borderRadius: 12,
    marginTop: 22,
    padding: 15,
  },
  buttonText: { color: "#fff", fontWeight: "700" },
  note: {
    color: "#62706F",
    fontSize: 12,
    lineHeight: 18,
    padding: 20,
    textAlign: "center",
  },
});
