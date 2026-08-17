class TextReport:

    def generate(self, state):

        version = state.get("version_validation", {})
        jira = state.get("jira_validation", {})

        output = []

        output.append("\n📊 RELEASE VALIDATION REPORT\n")

        # VERSION SECTION
        output.append("🔵 1. Latest Version Check")
        output.append(f"Latest version detected: {version.get('latest_version')}")

        if version.get("issues"):
            output.append("Status: ❌ ISSUES FOUND")
            for i in version["issues"]:
                output.append(f" - {i}")
        else:
            output.append("Status: ✅ VALID")
            output.append("Issues: None")

        output.append("")

        # JIRA SECTION
        output.append("🟣 2. JIRA VALIDATION (LATEST RELEASE ONLY)")
        output.append(f"Latest Release: {jira.get('latest_version')}")

        tickets = jira.get("tickets", [])

        if not tickets:
            output.append("jira ticket not found in pdf")
        else:
            for t in tickets:
                output.append(f"jira ticket found : {t['ticket']}")

        # SUMMARY
        output.append("\n🟡 FINAL SUMMARY")

        total = len(tickets)

        output.append(f"Total Tickets Found: {total}")

        output.append("\n====================")

        return "\n".join(output)