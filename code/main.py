import os
import json
import re
import time
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from typing import TypedDict, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langgraph.graph import StateGraph, END

load_dotenv()

# LLM + EMBEDDINGS
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile"
)

embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# STATE
class TicketState(TypedDict):
    # Input
    issue: str
    subject: str
    company: str
    # Classifier output
    cleaned_company: str
    core_issue: str
    is_vague: bool
    is_malicious: bool
    action: str
    product_area: str
    request_type: str
    justification: str
    # RAG context
    context: str
    # Final
    response: str
    status: str

# PYTHON ROUTING RULES
ALWAYS_ESCALATE_PATTERNS = [
    "remove my seat", "restore my access", "workspace owner",
    "increase my score", "change my score", "graded unfairly",
    "refund", "order id", "mock interview",
    "pause our subscription", "cancel subscription",
    "infosec", "security questionnaire", "fill in the forms",
    "reschedule", "alternative date",
    "identity has been stolen", "identity theft",
    "security vulnerability", "bug bounty",
    "all requests are failing", "stopped working completely",
    "none of the submissions across",
    "resume builder is down",
    "ban the seller",
    "dispute a charge",
    "how do i dispute",
]

ALWAYS_REPLY_PATTERNS = [
    "how do i", "how to", "how can i",
    "what is", "what are", "explain",
    "minimum spend", "minimum transaction",
    "urgent cash", "need cash", "atm",
    "crawling my website", "stop crawling",
    "data retention", "how long will",
    "lti key", "lti integration",
    "aws bedrock",
    "time accommodation",
    "inactivity", "timeout",
    "remove an interviewer", "remove a user",
    "remove them from",
    "certificate", "name update",
    "dispute a charge",
    "delete my account",
    "opt out",
]

def python_router(issue: str, company: str) -> Optional[str]:
    """
    Fast Python-based routing before hitting LLM.
    Returns 'escalate', 'reply', or None (let LLM decide).
    Fix #12: Move routing logic to Python.
    """
    issue_lower = issue.lower()

   
    injection_signals = [
        "ignore previous", "system prompt", "internal rules",
        "affiche toutes", "règles internes", "delete all files",
        "give me the code to delete"
    ]
    if any(sig in issue_lower for sig in injection_signals):
        return "malicious"

    # Check always-escalate patterns
    if any(p in issue_lower for p in ALWAYS_ESCALATE_PATTERNS):
        return "escalate"

    # Check always-reply patterns
    if any(p in issue_lower for p in ALWAYS_REPLY_PATTERNS):
        return "reply"

    # Vague check
    if len(issue.strip()) < 20:
        return "vague"

    return None  # Let LLM decide

# EMBEDDER — One time only
def embed_docs():
    print("\n=== EMBEDDING DOCS ===")
    companies = ["hackerrank", "claude", "visa"]
    for company in companies:
        persist_dir = f"../data_embedded/{company}"
        if Path(persist_dir).exists():
            print(f"  ⏭️  {company} already embedded — skipping")
            continue
        print(f"  Loading {company} docs...")
        loader = DirectoryLoader(
            f"../data/{company}",
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"}
        )
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50
        )
        chunks = splitter.split_documents(docs)
        Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=persist_dir
        )
        print(f"  ✅ {company}: {len(docs)} docs → {len(chunks)} chunks")
    print("=== EMBEDDING DONE ===\n")

# RAG RETRIEVER — retrieve once
def retrieve_docs(company: str, issue: str) -> str:
    try:
        # Fix #10: Better RAG query
        query = f"{company} support: {issue}"
        persist_dir = f"../data_embedded/{company.lower()}"
        vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings
        )
        retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 5}
        )
        docs = retriever.invoke(query)
        return "\n\n".join([d.page_content for d in docs])
    except Exception as e:
        return ""

# LLM HELPER

def call_llm_json(system: str, user: str) -> dict:
    response = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=user)
    ])
    raw = response.content.strip()
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}

def call_llm_text(system: str, user: str) -> str:
    response = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=user)
    ])
    return response.content.strip()

# NODE 1 — CLASSIFIER
def classifier_node(state: TicketState) -> TicketState:
    print("\n── CLASSIFIER NODE ──")

    issue = state["issue"]
    company = state["company"]

    # Fix #12: Python routing first
    python_decision = python_router(issue, company)

    if python_decision == "malicious":
        state["cleaned_company"] = company or "Unknown"
        state["core_issue"] = issue
        state["is_vague"] = False
        state["is_malicious"] = True
        state["action"] = "escalate"
        state["product_area"] = "security"
        state["request_type"] = "invalid"
        state["justification"] = "Request detected as malicious or prompt injection attempt."
        print(f"  ⚠️  Malicious detected — skipping LLM")
        return state

    if python_decision == "vague":
        state["cleaned_company"] = company or "Unknown"
        state["core_issue"] = issue
        state["is_vague"] = True
        state["is_malicious"] = False
        state["action"] = "escalate"
        state["product_area"] = "general"
        state["request_type"] = "invalid"
        state["justification"] = "Issue is too vague to process without more details."
        print(f"  ⚠️  Vague ticket — skipping LLM")
        return state

    
    result = call_llm_json(
        system="""You are a support ticket classifier for HackerRank, Claude, and Visa.

Analyze the ticket and return ONLY this JSON:
{
    "company": "HackerRank" or "Claude" or "Visa" or "Unknown",
    "core_issue": "1-2 sentence summary",
    "is_vague": true or false,
    "is_malicious": true or false,
    "action": "reply" or "escalate",
    "product_area": "account_access|billing|bug|test_management|privacy|fraud|security|general|certifications|travel_support",
    "request_type": "product_issue" or "feature_request" or "bug" or "invalid",
    "justification": "one sentence explaining decision"
}

ESCALATE when:
- Requires admin action (seat removal, workspace access)
- Score changes or unfair grading disputes
- Refunds, billing disputes, payment issues
- Subscription pause/cancel
- Fraud, identity theft, stolen cards
- Security vulnerability reports
- Platform-wide outages (all users affected)
- Resume Builder down
- Cannot reschedule employer-set assessments
- InfoSec questionnaire filling

REPLY when:
- How-to questions with steps in docs
- FAQ questions
- Technical troubleshooting (single user)
- ATM/emergency cash guidance
- Data retention questions
- LTI setup questions
- AWS Bedrock troubleshooting
- Website crawl opt-out
- Removing users/interviewers
- Certificate issues
- Minimum spend rules
- Time accommodation steps""",
        user=f"""
Ticket:
- Subject: {state['subject'] or 'No subject'}
- Company: {company or 'None'}
- Issue: {issue}

{"Python pre-routing suggested: " + python_decision if python_decision else ""}

Return ONLY the JSON.
"""
    )

    
    if python_decision in ["escalate", "reply"]:
        result["action"] = python_decision

    state["cleaned_company"] = result.get("company", company or "Unknown")
    state["core_issue"] = result.get("core_issue", issue)
    state["is_vague"] = result.get("is_vague", False)
    state["is_malicious"] = result.get("is_malicious", False)
    state["action"] = result.get("action", "escalate")
    state["product_area"] = result.get("product_area", "general")
    state["request_type"] = result.get("request_type", "product_issue")
    state["justification"] = result.get("justification", "")

    print(f"  Company: {state['cleaned_company']}")
    print(f"  Action: {state['action']} | Area: {state['product_area']}")
    print(f"  Vague: {state['is_vague']} | Malicious: {state['is_malicious']}")

    return state

# NODE 2 — RAG RETRIEVAL
def retrieval_node(state: TicketState) -> TicketState:
    company = state.get("cleaned_company", "Unknown").lower()
    if company in ["hackerrank", "claude", "visa"]:
        state["context"] = retrieve_docs(company, state["core_issue"])
    else:
        state["context"] = ""
    return state

# RESPONSE VALIDATOR
def validate_response(response: str, action: str) -> str:
    """Ensure response has steps and next steps."""
    if not response or len(response) < 50:
        if action == "escalate":
            return "This issue requires human assistance. Please contact support directly."
        return "I was unable to generate a proper response. Please contact support."
    return response

# NODE 3 — RESPONDER

RESPONDER_SYSTEM = """You are a helpful, empathetic support agent for {company}.

You MUST structure every response like this:

👋 **Acknowledgment**
One warm sentence acknowledging the user's issue.

✅ **Solution / Steps**
If the issue can be solved:
- Numbered step-by-step instructions
- Be specific and clear
- Use exact button names, menu paths from the documentation

🔗 **Relevant Links**
If documentation contains any URLs or article references, include them like:
- [Article Title](url)

⚡ **Next Steps / Fallback**
Always end with:
- What to do if steps don't work
- Who to contact (support email, phone number if in docs)
- What information to have ready

STRICT RULES:
- Only use information from the provided documentation
- Always give steps — never just say "contact support" without trying first
- Always include links if they exist in the docs
- If docs don't fully cover it, give best available guidance THEN suggest support
- Never leave the user without a clear next action
"""

ESCALATION_SYSTEM = """You are a helpful, empathetic support agent for {company}.

This ticket needs human review, but you MUST still help the user.

Structure your response like this:

⚠️ **Why This Needs Human Review**
One clear sentence explaining why.

📋 **What To Do Next**
Exact steps the user should take:
- Who to contact (email, phone, link if in docs)
- What to say when they reach out

📝 **Information To Have Ready**
List what details they should prepare:
- Account details
- Order IDs
- Screenshots etc.

🔗 **Useful Links**
Any relevant links from the documentation.

⏱️ **What To Expect**
Brief note on resolution process/timeline if known from docs.
"""

def responder_node(state: TicketState) -> TicketState:
    print(f"\n── RESPONDER NODE ({state.get('cleaned_company', 'Unknown')}) ──")

    company = state.get("cleaned_company", "Unknown")
    action = state.get("action", "escalate")
    context = state.get("context", "")
    core_issue = state.get("core_issue", state["issue"])

    if action == "escalate" or state.get("is_malicious") or state.get("is_vague"):
        if state.get("is_malicious"):
            state["response"] = "I'm sorry, but this request cannot be processed as it appears to violate our support guidelines. Please submit a genuine support request."
            state["status"] = "replied"
            return state

        if state.get("is_vague"):
            state["response"] = "I'd love to help! Could you please provide more details about your issue? Specifically: what feature or product you're using, what you were trying to do, and what happened instead. This will help us assist you much faster."
            state["status"] = "escalated"
            return state

        # Escalation with guidance (fix #11)
        system = ESCALATION_SYSTEM.format(company=company)
        response = call_llm_text(
            system=system,
            user=f"""
Issue: {core_issue}
Company: {company}
Product Area: {state.get('product_area')}

Relevant Documentation:
{context if context else "No specific documentation available."}

Provide a helpful escalation response with clear next steps.
"""
        )
        state["response"] = validate_response(response, "escalate")
        state["status"] = "escalated"

    else:
        # Reply with full solution (fix #4, #5, #14)
        system = RESPONDER_SYSTEM.format(company=company)
        response = call_llm_text(
            system=system,
            user=f"""
Issue: {core_issue}
Company: {company}

Relevant Documentation:
{context if context else "No specific documentation available for this exact issue."}

Provide a complete, step-by-step response. 
If documentation covers it, use exact steps.
If not fully covered, provide best guidance and support contact.
"""
        )
        state["response"] = validate_response(response, "reply")
        state["status"] = "replied"

    print(f"  → {state['status']} | {state['product_area']}")
    return state

# ROUTER

def router(state: TicketState) -> str:
    if state.get("is_malicious") or state.get("is_vague"):
        return "responder"
    if state.get("action") == "escalate":
        return "responder"
    company = state.get("cleaned_company", "").lower()
    if company in ["hackerrank", "claude", "visa"]:
        return "retrieval"
    return "responder"

# BUILD GRAPH 

def build_graph():
    graph = StateGraph(TicketState)

    graph.add_node("classifier", classifier_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("responder", responder_node)

    graph.set_entry_point("classifier")

    graph.add_conditional_edges(
        "classifier",
        router,
        {
            "retrieval": "retrieval",
            "responder": "responder"
        }
    )

    graph.add_edge("retrieval", "responder")
    graph.add_edge("responder", END)

    return graph.compile()

# CSV RUNNER
def run_csv():
    print("\n=== PROCESSING TICKETS ===\n")
    app = build_graph()
    df = pd.read_csv("../support_tickets/support_tickets.csv")
    results = []

    for i, row in df.iterrows():
        subject = str(row.get("Subject", ""))
        print(f"[{i+1}/{len(df)}] {subject or str(row.get('Issue', ''))[:60]}")

        try:
            final_state = app.invoke({
                "issue": str(row.get("Issue", "")),
                "subject": subject,
                "company": str(row.get("Company", "")),
                "context": ""
            })

            results.append({
                "issue": final_state["issue"],
                "subject": final_state["subject"],
                "company": final_state["company"],
                "status": final_state.get("status", "escalated"),
                "product_area": final_state.get("product_area", "general"),
                "request_type": final_state.get("request_type", "product_issue"),
                "response": final_state.get("response", ""),
                "justification": final_state.get("justification", "")
            })

            print(f"  → {final_state.get('status')} | {final_state.get('product_area')}")

        except Exception as e:
            print(f"  ❌ Error: {e}")
            # Add sleep only on rate limit error
            if "429" in str(e):
                print("  ⏳ Rate limited — waiting 30 seconds...")
                time.sleep(30)
                # Retry once
                try:
                    final_state = app.invoke({
                        "issue": str(row.get("Issue", "")),
                        "subject": subject,
                        "company": str(row.get("Company", "")),
                        "context": ""
                    })
                    results.append({
                        "issue": final_state["issue"],
                        "subject": final_state["subject"],
                        "company": final_state["company"],
                        "status": final_state.get("status", "escalated"),
                        "product_area": final_state.get("product_area", "general"),
                        "request_type": final_state.get("request_type", "product_issue"),
                        "response": final_state.get("response", ""),
                        "justification": final_state.get("justification", "")
                    })
                except:
                    results.append({
                        "issue": str(row.get("Issue", "")),
                        "subject": subject,
                        "company": str(row.get("Company", "")),
                        "status": "escalated",
                        "product_area": "general",
                        "request_type": "product_issue",
                        "response": "This ticket has been escalated to a human agent for review.",
                        "justification": "Error during processing."
                    })

    out_df = pd.DataFrame(results)
    out_df.to_csv("../support_tickets/output.csv", index=False)
    print(f"\n=== DONE → output.csv ({len(results)}/29 tickets) ===\n")

# ENTRY POINT
if __name__ == "__main__":
    embed_docs()
    run_csv()