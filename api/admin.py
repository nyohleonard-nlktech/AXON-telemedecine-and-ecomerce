from django.contrib import admin
from .models import User, Product, Order, PickDrop, Chat, Message, MedConsult, Notification

admin.site.register(User)
admin.site.register(Product)
admin.site.register(Order)
admin.site.register(PickDrop)
admin.site.register(Chat)
admin.site.register(Message)
admin.site.register(MedConsult)
admin.site.register(Notification)
