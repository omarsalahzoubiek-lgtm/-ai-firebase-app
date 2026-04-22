import os
import json
import uuid  # مكتبة لإنشاء ID فريد لكل محادثة
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
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Firebase: {e}")

# ==========================================
# مسارات الموقع (Routes)
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

# 1. مسار التحدث (بذاكرة)
@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get("question", "").strip()
    chat_id = data.get("chat_id")  # جلب رقم المحادثة الحالية (إن وجد)

    if not user_question:
        return jsonify({"error": "الرجاء كتابة سؤال"}), 400

    try:
        # الإعداد الافتراضي للرسائل
        messages =[{"role": "system", "content": "أنت مساعد ذكي ومفيد وتتحدث العربية بطلاقة. تذكر سياق المحادثة السابقة وأجب بناءً عليه."}]
        title = user_question[:40] # عنوان المحادثة هو أول 40 حرف من أول سؤال

        # إذا كانت المحادثة موجودة مسبقاً، نجلب رسائلها من Firebase ليتذكرها الذكاء الاصطناعي
        if chat_id:
            chat_ref = db.collection("chat_sessions").document(chat_id)
            chat_doc = chat_ref.get()
            if chat_doc.exists:
                chat_data = chat_doc.to_dict()
                for msg in chat_data.get("messages",[]):
                    messages.append(msg)
                title = chat_data.get("title", title)
        else:
            # إذا لم تكن موجودة، ننشئ رقم ID جديد للمحادثة
            chat_id = str(uuid.uuid4())

        # إضافة السؤال الجديد للقائمة
        messages.append({"role": "user", "content": user_question})

        # إرسال كل المحادثة إلى LLaMA
        response = client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile",
            temperature=0.7,
        )
        ai_answer = response.choices[0].message.content

        # إضافة رد الذكاء الاصطناعي للقائمة
        messages.append({"role": "assistant", "content": ai_answer})

        # حفظ أو تحديث المحادثة في Firebase (بدون دور الـ system لتقليل المساحة)
        db_messages = [m for m in messages if m["role"] != "system"]
        db.collection("chat_sessions").document(chat_id).set({
            "chat_id": chat_id,
            "title": title,
            "messages": db_messages,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

        # نرد على الواجهة بالإجابة + رقم المحادثة لكي تتذكره في السؤال القادم
        return jsonify({"answer": ai_answer, "chat_id": chat_id})
    
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return jsonify({"error": "حدث خطأ داخلي في الخادم."}), 500

# 2. مسار جلب قائمة المحادثات (للشريط الجانبي)
@app.route('/history', methods=['GET'])
def get_history():
    try:
        # جلب آخر 20 محادثة مرتبة من الأحدث للأقدم
        chats_ref = db.collection("chat_sessions").order_by("updated_at", direction=firestore.Query.DESCENDING).limit(20)
        results = chats_ref.stream()

        chats =[]
        for doc in results:
            data = doc.to_dict()
            chats.append({
                "chat_id": data.get("chat_id"),
                "title": data.get("title", "محادثة بدون عنوان")
            })

        return jsonify({"history": chats})
    except Exception as e:
        return jsonify({"error": "تعذر جلب السجل"}), 500

# 3. مسار جلب محتوى محادثة سابقة كاملة
@app.route('/chat/<chat_id>', methods=['GET'])
def get_chat(chat_id):
    try:
        chat_doc = db.collection("chat_sessions").document(chat_id).get()
        if chat_doc.exists:
            return jsonify(chat_doc.to_dict())
        return jsonify({"error": "المحادثة غير موجودة"}), 404
    except Exception as e:
        return jsonify({"error": "تعذر جلب المحادثة"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)
