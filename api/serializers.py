from rest_framework import serializers
from django.conf import settings
from .models import User, Product, Order, PickDrop, Chat, Message, MedConsult, Notification, Prescription


class UserSerializer(serializers.ModelSerializer):
    is_admin     = serializers.SerializerMethodField()
    profile_pic_url = serializers.SerializerMethodField()
    logo_url     = serializers.SerializerMethodField()
    id_front_url = serializers.SerializerMethodField()
    id_back_url  = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id','username','email','first_name','last_name','role','phone',
                  'biz_name','zone','med_role','status','conditions','expires_at',
                  'is_verified', 'is_admin','profile_pic_url','logo_url','id_front_url','id_back_url']

    def get_is_admin(self, obj):
        return obj.email in getattr(settings, 'ADMIN_EMAILS', [])

    def _abs(self, request, field_value):
        if not field_value:
            return None
        if request:
            return request.build_absolute_uri(field_value.url)
        return field_value.url

    def get_profile_pic_url(self, obj):
        return self._abs(self.context.get('request'), obj.profile_pic)

    def get_logo_url(self, obj):
        return self._abs(self.context.get('request'), obj.logo)

    def get_id_front_url(self, obj):
        return self._abs(self.context.get('request'), obj.id_front)

    def get_id_back_url(self, obj):
        return self._abs(self.context.get('request'), obj.id_back)


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id','vendor_id','vendor_name','name','desc','category',
                  'price','stock','emoji','is_medical','image_url','created_at']

    def get_image_url(self, obj):
        req = self.context.get('request')
        if obj.image and req:
            return req.build_absolute_uri(obj.image.url)
        return None


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Order
        fields = '__all__'


class PickDropSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PickDrop
        fields = '__all__'


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Message
        fields = ['id','chat_id','text','sender_type','sender_name','created_at']


class ChatSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()

    class Meta:
        model  = Chat
        fields = ['id','booking_id','customer_name','phone','chat_type','consult_type',
                  'address','pickup_text','drop_text','pickup_lat','pickup_lng',
                  'drop_lat','drop_lng','created_at','last_message']

    def get_last_message(self, obj):
        msg = obj.messages.last()
        return msg.text[:80] if msg else ''


class PrescriptionSerializer(serializers.ModelSerializer):
    doctor_name = serializers.ReadOnlyField(source='doctor.first_name')

    class Meta:
        model = Prescription
        fields = ['id', 'consult', 'doctor', 'doctor_name', 'medication', 'dosage', 'frequency', 'duration', 'instructions', 'created_at']


class MedConsultSerializer(serializers.ModelSerializer):
    prescriptions = PrescriptionSerializer(many=True, read_only=True)

    class Meta:
        model  = MedConsult
        fields = ['id', 'booking_id', 'patient_name', 'patient_age', 'patient_weight', 
                  'allergies', 'current_meds', 'consult_type', 'symptoms', 'status', 
                  'assigned_to', 'chat', 'created_at', 'prescriptions']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Notification
        fields = '__all__'
