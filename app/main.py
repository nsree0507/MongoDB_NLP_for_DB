from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from nlp.intent_model import IntentModel
from nlp.embedding_model import EmbeddingModel
from nlp.schema_matcher import SchemaMatcher
from query_engine.query_builder import QueryBuilder
from db.connection import MongoConnection
import pandas as pd
import io
import json

# -----------------------------------------------------
# FastAPI App
# -----------------------------------------------------

app = FastAPI(title="MongoDB NLP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------
# Initialize Components (Load Once)
# -----------------------------------------------------
last_uploaded_collection = None
intent_model = IntentModel()
embedding_model = EmbeddingModel()
schema_matcher = SchemaMatcher(embedding_model)
query_builder = QueryBuilder()
db = MongoConnection()


# -----------------------------------------------------
# 🔥 Response Formatter (NEW)
# -----------------------------------------------------

def format_response(intent, results):
    if not results:
        return "No records found."

    sentences = []

    if intent == "find":
        for item in results:
            name = item.get("name", "Unknown")
            dept = item.get("department", "Unknown department")
            salary = item.get("salary", "N/A")

            sentence = f"{name} works in {dept} department and earns ₹{salary}."
            sentences.append(sentence)

        return " ".join(sentences)

    elif intent == "aggregate":
        # For aggregation results
        if len(results) == 1:
            key, value = list(results[0].items())[0]
            return f"The {key} is {value}."

        return f"The query returned {len(results)} aggregated results."

    return "Query executed successfully."


# -----------------------------------------------------
# 📊 Chart Suggestion Engine (NEW)
# -----------------------------------------------------

def suggest_chart(intent, user_query):
    user_query = user_query.lower()

    if "count" in user_query or "how many" in user_query:
        return "pie"

    if "average" in user_query or "mean" in user_query:
        return "bar"

    if "trend" in user_query or "over time" in user_query:
        return "line"

    if "highest" in user_query or "top" in user_query:
        return "bar"

    if intent == "find":
        return "table"

    return "table"


# -----------------------------------------------------
# Root Endpoint
# -----------------------------------------------------

@app.get("/")
def root():
    return {"message": "MongoDB NLP API is running successfully 🚀"}


# -----------------------------------------------------
# Query Endpoint
# -----------------------------------------------------

@app.get("/query")
def process_query(user_query: str):
    try:
        # 1️⃣ Detect intent using ML model
        intent, confidence_score = intent_model.predict(user_query)
        # -------------------------------------------------
        # 🔥 Smart Intent Correction Layer (Hybrid AI)
        # -------------------------------------------------
        user_query_lower = user_query.lower()
        if any(word in user_query_lower for word in
               ["highest", "lowest", "descending", "ascending", "sorted"]):
            intent = "find"
        if (
            any(word in user_query_lower for word in ["above", "below", "greater than", "less than"])
            and not any(word in user_query_lower for word in
                        ["total", "sum", "average", "mean", "count"])
        ):
            intent = "find"
        if any(word in user_query_lower for word in
               ["total", "sum", "average", "mean", "count", "how many"]):
            intent = "aggregate"
        # -------------------------------------------------
        # 2️⃣ Schema matching
        collection, field = schema_matcher.match(user_query)
        global last_uploaded_collection
        # 🔥 Force query to use last uploaded collection if exists
        if last_uploaded_collection:
            collection = last_uploaded_collection
        # -------------------------------------------------
        # 🔥 NEW: Dynamic Collection Detection
        # -------------------------------------------------
        user_query_lower = user_query.lower()
        if "from" in user_query_lower:
            words = user_query_lower.split()
            if "from" in words:
                idx = words.index("from")
                if idx + 1 < len(words):
                    collection = words[idx + 1]
        # 3️⃣ Build MongoDB query
        mongo_query = query_builder.build(
            intent,
            collection,
            field,
            user_query
        )
        # 4️⃣ Execute query
        result = db.execute(mongo_query)
        if not isinstance(result, list):
            result = list(result)
        # Convert ObjectId to string
        from bson import ObjectId
        for doc in result:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        # -------------------------------------------------
        # 🔥 NEW LAYERS ADDED HERE
        # -------------------------------------------------
        english_summary = format_response(intent, result)
        chart_type = suggest_chart(intent, user_query)
        # -------------------------------------------------
        return {
            "status": "success",
            "user_query": user_query,
            "intent": intent,
            "collection": collection,
            "field": field,
            "mongo_query": mongo_query,
            "result_count": len(result),
            "confidence": confidence_score,
            "summary": english_summary,
            "chart_type": chart_type,
            "result": result
        }
    except Exception as e:
        import traceback
        print("===== ERROR START =====")
        traceback.print_exc()
        print("===== ERROR END =====")
        raise e

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    filename = file.filename.lower()
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(contents.decode("utf-8")))
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))
        elif filename.endswith(".json"):
            data = json.loads(contents.decode("utf-8"))
            df = pd.DataFrame(data)
        else:
            return {"status": "error", "message": "Unsupported file type"}
        records = df.to_dict(orient="records")
        collection_name = file.filename.split(".")[0]
        db.db[collection_name].delete_many({})  # clear old data
        db.db[collection_name].insert_many(records)
        global last_uploaded_collection
        last_uploaded_collection = collection_name
        return {
            "status": "success",
            "collection": collection_name,
            "rows_inserted": len(records)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
