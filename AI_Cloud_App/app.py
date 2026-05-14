import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# الاتصال بـ Firebase
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
# المسارات (Routes)
# ==========================================
@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get("question", "").strip()
    image_url = data.get("image_url", "")
    uid = data.get("uid")
    context = data.get("context", [])
    session_id = data.get("session_id") # 👈 استلام رقم المحادثة الحالية

    if not user_question and not image_url: 
        return jsonify({"error": "الرجاء كتابة سؤال أو رفع صورة"}), 400
    if not uid: 
        return jsonify({"error": "غير مصرح لك. يرجى تسجيل الدخول."}), 401

    # إعداد شخصية المساعد
    messages = [{"role": "system", "content": "أنت مساعد ذكي ومفيد وتتحدث العربية بطلاقة. أجب بدقة بناءً على سياق المحادثة."}]
    
    # إضافة الذاكرة السابقة
    for msg in context[-10:]:
        messages.append(msg)
    
    # إضافة السؤال الحالي
    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_question if user_question else "اشرح ما في هذه الصورة بالتفصيل."},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
        model_name = "meta-llama/llama-4-scout-17b-16e-instruct" 
    else:
        messages.append({"role": "user", "content": user_question})
        model_name = "llama-3.3-70b-versatile"

    try:
        # طلب الإجابة من الذكاء الاصطناعي
        response = client.chat.completions.create(
            messages=messages,
            model=model_name,
            temperature=0.7,
        )
        ai_answer = response.choices[0].message.content

        # 🧠 نظام الجلسات (Sessions) الجديد
        if not session_id:
            # إذا لم يكن هناك رقم محادثة، ننشئ محادثة جديدة في Firebase
            new_session_ref = db.collection("chat_sessions").document()
            session_id = new_session_ref.id
            
            # عنوان المحادثة يكون أول 40 حرف من أول سؤال
            title = user_question[:40] + "..." if len(user_question) > 40 else user_question
            if not title: title = "محادثة صورة/ملف"

            new_session_ref.set({
                "uid": uid,
                "title": title,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "messages": [
                    {"role": "user", "content": user_question, "image_url": image_url},
                    {"role": "assistant", "content": ai_answer}
                ]
            })
        else:
            # إذا كانت المحادثة موجودة، نضيف الرسائل الجديدة إليها فقط
            session_ref = db.collection("chat_sessions").document(session_id)
            session_ref.update({
                "updated_at": firestore.SERVER_TIMESTAMP,
                "messages": firestore.ArrayUnion([
                    {"role": "user", "content": user_question, "image_url": image_url},
                    {"role": "assistant", "content": ai_answer}
                ])
            })

        # إرسال الإجابة ورقم الجلسة للمتصفح
        return jsonify({"answer": ai_answer, "session_id": session_id})
        
    except Exception as e:
        print(f"❌ خطأ في معالجة الذكاء الاصطناعي: {str(e)}")
        return jsonify({"error": f"حدث خطأ في معالجة الذكاء الاصطناعي: {str(e)}"}), 500

@app.route('/history', methods=['GET'])
def get_history():
    uid = request.args.get('uid')
    if not uid: return jsonify({"sessions": []})

    try:
        # جلب كل المحادثات الخاصة بالمستخدم
        sessions_ref = db.collection("chat_sessions").where("uid", "==", uid).stream()
        sessions = []
        for doc in sessions_ref:
            d = doc.to_dict()
            time_val = d.get('updated_at').timestamp() if d.get('updated_at') else 0
            sessions.append({
                "session_id": doc.id,
                "title": d.get("title", "محادثة جديدة"),
                "messages": d.get("messages", []),
                "time_val": time_val
            })
            
        # ترتيب المحادثات من الأحدث للأقدم لتظهر في القائمة الجانبية
        sessions.sort(key=lambda x: x['time_val'], reverse=True)
        
        # إزالة قيمة الوقت قبل إرسالها لتجنب أخطاء JSON
        for s in sessions:
            del s['time_val']
            
        return jsonify({"sessions": sessions})
    except Exception as e:
        print(f"❌ خطأ في جلب السجل: {e}")
        return jsonify({"error": "تعذر جلب السجل"}), 500

@app.route('/track', methods=['POST'])
def track_visitor():
    try:
        ip = request.headers.getlist("X-Forwarded-For")[0] if request.headers.getlist("X-Forwarded-For") else request.remote_addr
        db.collection("visitors").add({
            "ip_address": ip,
            "device_info": request.headers.get('User-Agent'),
            "visited_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"status": "tracked"})
    except Exception:
        return jsonify({"error": "error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)
