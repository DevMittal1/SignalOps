# 🎭 Testing Script: Pipeline Review with Aarav

Use this script/cheat-sheet to test the Voice AI Agent. It is built directly from the dynamic context in `prompts.py` so the agent's retrieved context and tool logic align perfectly with your responses.

---

## 👤 Your Persona: Aarav (Account Executive)
*   **Role**: AE, Enterprise East team
*   **Manager**: Priya
*   **Performance Profile**: Strong at discovery, but historically optimistic in late-stage deals and often slips close dates (average of 14 slip days).
*   **Deal Under Review**: **Acme Renewal Expansion** ($180,000, currently in "Proposal" stage).

---

## 📈 Opportunity Context: Acme Renewal Expansion
*   **Target Close Date**: June 18, 2026 (shifted 4 times in the last 90 days).
*   **Customer Key Contacts**: 
    *   **Nina** (Champion, Director of Ops - High Influence)
    *   **Jordan** (Security Contact, IT Manager - Medium Influence)
    *   **Rohit** (Economic Buyer, VP Finance - High Influence, but no meeting confirmed yet).
*   **The Known Blocker**: Customer is waiting on security architecture documents and a SOC2 evidence timeline.
*   **The Internal Blocker**: You (Aarav) are responsible for these documents but haven't sent them yet because you've been busy.

---

## 💬 Dialogue Script & Test Flows

Choose one of the flows below when interacting with the agent:

### Flow A: Happy Path (Cooperative AE)
*   **Agent**: "Hi Aarav, this is the AI Revenue Operations assistant. Do you have 3-5 minutes for a pipeline check on the Acme Renewal Expansion deal?"
*   **You**: "Yeah, sure. I have a few minutes."
*   **Agent**: "Great. I see the Acme Renewal Expansion deal is in the Proposal stage for $180,000, with a close date of June 18th. What is the main blocker keeping this from moving to the next stage?"
*   **You**: "We're waiting on security review. Jordan, their IT Manager, requested security architecture documents and our SOC2 evidence timeline."
*   **Agent**: "Who is responsible for preparing and sending those architecture documents?"
*   **You**: "I am responsible for that."
*   **Agent**: "Have they been sent over yet?"
*   **You**: "No, not yet. I've been caught up with other deals, so I haven't prepared them yet."
*   **Agent**: "When do you plan to send them?"
*   **You**: "I'll get them sent over by this Friday."
*   **Agent**: "Got it. And have you confirmed a meeting with the economic buyer, Rohit, yet?"
*   **You**: "No, not yet. Nina is trying to help me schedule that."
*   **Agent**: "Alright, let's recap..." *(Let the agent summarize and confirm)*

---

### Flow B: Drill-Down Test (Vague AE)
*Use this flow to test if the agent successfully flags vague answers and uses the `get_static_followup` tool.*

*   **Agent**: "...What is the main blocker keeping this from moving to the next stage?"
*   **You**: "It's just standard review. They're reviewing it." *(Vague Statement 1)*
*   **Agent**: *(Should execute `get_static_followup`)* -> "What specifically are they reviewing, and who owns that review on their side?"
*   **You**: "Their IT team is looking at security."
*   **Agent**: "Have we sent all the required materials to them?"
*   **You**: "We're working on it." *(Vague Statement 2)*
*   **Agent**: -> "What exact result are they waiting for, and has a concrete timeline been shared with you?"
*   **You**: "They need the architecture documents from us. I have to prepare them, but haven't had the time yet."
*   **Agent**: "When will you be able to send those over?"
*   **You**: "Hopefully by early next week."

---

## 🛠️ Verification Checklist for the Tester
1.  **Greeting & Context**: Does the agent state the duration (3-5 mins) and refer to the correct deal (Acme Renewal Expansion, $180k)?
2.  **Tool Executions**:
    *   Watch the terminal output. Does the agent call `get_deal_context` or `get_rep_context`?
    *   When you give vague answers, does the agent call `get_static_followup`?
    *   During the conversation, does the agent call `append_call_fact` to record facts like `"Architecture documents not prepared"`?
    *   At the end of the call, does the agent call `save_call_summary` with the correct blocker, root cause, and evidence?
