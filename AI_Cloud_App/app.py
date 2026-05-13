import os
import json
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# الاتصال بقاعدة بيانات Firebase
# ==========================================
try:
    firebase_cred_json = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred_json:
        cred_dict = json.loads(firebase_cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ تم الاتصال بـ Firebase بنجاح")
    else:
        print("⚠️ تحذير: مفاتيح Firebase غير موجودة.")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Firebase: {e}")

# ==========================================
# المسارات الأساسية
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

# 1. مسار المحادثة
@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get("question", "").strip()
    if not user_question: return jsonify({"error": "الرجاء كتابة سؤال"}), 400

    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "أنت مساعد ذكي ومفيد وتتحدث العربية بطلاقة."},
                {"role": "user", "content": user_question}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
        )
        ai_answer = response.choices[0].message.content

        chat_document = {
            "question": user_question,
            "answer": ai_answer,
            "timestamp": firestore.SERVER_TIMESTAMP 
        }
        db.collection("chats").add(chat_document)

        return jsonify({"answer": ai_answer})
    except Exception as e:
        return jsonify({"error": "حدث خطأ داخلي."}), 500

# 2. مسار جلب السجل
@app.route('/history', methods=['GET'])
def get_history():
    try:
        chats_ref = db.collection("chats").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(15)
        chats = [{"question": doc.to_dict().get("question", ""), "answer": doc.to_dict().get("answer", "")} for doc in chats_ref.stream()]
        chats.reverse()
        return jsonify({"history": chats})
    except Exception as e:
        return jsonify({"error": "تعذر جلب السجل"}), 500

# ==========================================
# الميزة الجديدة: مسار تتبع الزوار (Analytics)
# ==========================================
@app.route('/track', methods=['POST'])
def track_visitor():
    try:
        # جلب عنوان IP (يعمل حتى لو كان التطبيق على Render)
        if request.headers.getlist("X-Forwarded-For"):
            ip = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip = request.remote_addr

        # جلب بيانات المتصفح ونظام التشغيل
        user_agent = request.headers.get('User-Agent')

        # حفظ بيانات الزائر في Firebase في جدول "visitors"
        visitor_data = {
            "ip_address": ip,
            "device_info": user_agent,
            "visited_at": firestore.SERVER_TIMESTAMP
        }
        db.collection("visitors").add(visitor_data)
        
        return jsonify({"status": "tracked"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)
