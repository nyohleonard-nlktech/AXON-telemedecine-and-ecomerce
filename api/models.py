from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLES    = [('customer','Customer'),('vendor','Vendor'),('medical','Medical'),('patient','Patient')]
    STATUSES = [('pending','Pending'),('active','Active')]
    MED_ROLES= [('doctor','Doctor'),('nurse','Nurse'),('pharmacist','Pharmacist')]

    role        = models.CharField(max_length=20, choices=ROLES, default='customer')
    phone       = models.CharField(max_length=25, blank=True)
    biz_name    = models.CharField(max_length=200, blank=True)
    zone        = models.CharField(max_length=100, blank=True)
    med_role    = models.CharField(max_length=20, choices=MED_ROLES, blank=True)
    profile_pic = models.ImageField(upload_to='profiles/', blank=True, null=True)
    logo        = models.ImageField(upload_to='logos/', blank=True, null=True)
    id_front    = models.ImageField(upload_to='ids/', blank=True, null=True)
    id_back     = models.ImageField(upload_to='ids/', blank=True, null=True)
    status      = models.CharField(max_length=20, choices=STATUSES, default='active')
    conditions  = models.TextField(blank=True)   # patient health conditions
    expires_at  = models.DateTimeField(blank=True, null=True)  # 40-day window
    is_verified = models.BooleanField(default=False)  # Verified tick status

    class Meta:
        db_table = 'users'


class Product(models.Model):
    vendor      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='products')
    vendor_name = models.CharField(max_length=200)
    name        = models.CharField(max_length=200)
    desc        = models.TextField(blank=True)
    category    = models.CharField(max_length=100, default='Other')
    price       = models.PositiveIntegerField()
    stock       = models.PositiveIntegerField(default=1)
    emoji       = models.CharField(max_length=10, default='📦')
    image       = models.ImageField(upload_to='products/', blank=True, null=True)
    is_medical  = models.BooleanField(default=False)  # True = OTC drug
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Order(models.Model):
    STATUSES = [('pending','Pending'),('processing','Processing'),('delivered','Delivered'),('cancelled','Cancelled')]
    ESCROW   = [('held','Held'),('released','Released'),('refunded','Refunded')]
    METHODS  = [('drone','Drone'),('rider','Rider'),('pickup','Pickup')]

    customer      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=200)
    phone         = models.CharField(max_length=25)
    address       = models.TextField()
    delivery_lat  = models.FloatField(null=True, blank=True)
    delivery_lng  = models.FloatField(null=True, blank=True)
    delivery_method = models.CharField(max_length=20, choices=METHODS, default='rider')
    items         = models.JSONField(default=list)  # [{id, name, price, qty, vendorName}]
    subtotal      = models.PositiveIntegerField(default=0)
    commission    = models.PositiveIntegerField(default=0)
    delivery_fee  = models.PositiveIntegerField(default=800)
    total         = models.PositiveIntegerField(default=0)
    status        = models.CharField(max_length=20, choices=STATUSES, default='pending')
    escrow_status = models.CharField(max_length=20, choices=ESCROW, default='held')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class PickDrop(models.Model):
    STATUSES  = [('pending_review','Pending Review'),('approved','Approved'),('dispatching','Dispatching'),('delivered','Delivered')]
    SECURITY  = [('screening','Screening'),('approved','Approved'),('rejected','Rejected')]
    TYPES     = [('commerce','Commerce'),('medical','Medical'),('document','Document'),('food','Food')]

    customer             = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    customer_name        = models.CharField(max_length=200)
    customer_phone       = models.CharField(max_length=25)
    description          = models.TextField()
    estimated_value      = models.PositiveIntegerField(default=0)
    item_type            = models.CharField(max_length=20, choices=TYPES, default='commerce')
    pickup_text          = models.TextField()
    pickup_lat           = models.FloatField(null=True, blank=True)
    pickup_lng           = models.FloatField(null=True, blank=True)
    pickup_contact_name  = models.CharField(max_length=200, blank=True)
    pickup_contact_phone = models.CharField(max_length=25, blank=True)
    drop_text            = models.TextField()
    drop_lat             = models.FloatField(null=True, blank=True)
    drop_lng             = models.FloatField(null=True, blank=True)
    drop_contact_name    = models.CharField(max_length=200, blank=True)
    drop_contact_phone   = models.CharField(max_length=25, blank=True)
    status               = models.CharField(max_length=30, choices=STATUSES, default='pending_review')
    security_status      = models.CharField(max_length=20, choices=SECURITY, default='screening')
    created_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Chat(models.Model):
    TYPES = [('order','Order'),('pickdrop','PickDrop'),('medical_consult','Medical Consult')]

    booking_id   = models.CharField(max_length=50, unique=True)
    customer_name= models.CharField(max_length=200)
    phone        = models.CharField(max_length=25, blank=True)
    chat_type    = models.CharField(max_length=30, choices=TYPES)
    consult_type = models.CharField(max_length=20, blank=True)   # doctor/nurse/pharmacist
    address      = models.TextField(blank=True)
    pickup_text  = models.TextField(blank=True)
    drop_text    = models.TextField(blank=True)
    pickup_lat   = models.FloatField(null=True, blank=True)
    pickup_lng   = models.FloatField(null=True, blank=True)
    drop_lat     = models.FloatField(null=True, blank=True)
    drop_lng     = models.FloatField(null=True, blank=True)
    assigned_to  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Message(models.Model):
    SENDERS = [('system','System'),('admin','Admin'),('customer','Customer'),('vendor','Vendor'),('medical','Medical')]

    chat        = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    text        = models.TextField()
    sender_type = models.CharField(max_length=20, choices=SENDERS, default='customer')
    sender_name = models.CharField(max_length=200, default='')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class MedConsult(models.Model):
    STATUSES = [('queued','Queued'),('active','Active'),('closed','Closed')]

    booking_id   = models.CharField(max_length=50, unique=True)
    patient_name = models.CharField(max_length=200)
    patient_age  = models.PositiveIntegerField(null=True, blank=True)
    patient_weight = models.FloatField(null=True, blank=True)
    allergies    = models.TextField(blank=True)
    current_meds = models.TextField(blank=True)
    consult_type = models.CharField(max_length=20)
    symptoms     = models.TextField()
    status       = models.CharField(max_length=20, choices=STATUSES, default='queued')
    assigned_to  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    chat         = models.ForeignKey(Chat, on_delete=models.SET_NULL, null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Notification(models.Model):
    to_user      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notif_type   = models.CharField(max_length=50)
    chat_id      = models.CharField(max_length=50, blank=True)
    patient_name = models.CharField(max_length=200, blank=True)
    consult_type = models.CharField(max_length=20, blank=True)
    symptoms     = models.TextField(blank=True)
    read         = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Prescription(models.Model):
    consult      = models.ForeignKey(MedConsult, on_delete=models.CASCADE, related_name='prescriptions')
    doctor       = models.ForeignKey(User, on_delete=models.CASCADE)
    medication   = models.CharField(max_length=255)
    dosage       = models.CharField(max_length=100)
    frequency    = models.CharField(max_length=100)
    duration     = models.CharField(max_length=100)
    instructions = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
