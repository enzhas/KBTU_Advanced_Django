from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal, engine, User, Product, Order, Category, Review
from typing import List
import time
from kafka import KafkaProducer, KafkaConsumer
import json
from pydantic import BaseModel
import dramatiq

# Initialize FastAPI app
app = FastAPI()

# Kafka configuration
KAFKA_BOOTSTRAP_SERVER = 'localhost:9092'
KAFKA_TOPIC = 'logs'

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class OrderCreate(BaseModel):
    user_id: int
    products: List[int]
    email: str

class UserCreate(BaseModel):
    username: str
    email: str
    password_hash: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str

# Function to calculate total price of an order
def calculate_total_price(order_data: OrderCreate, products: List[Product]):
    total_price = sum(product.price for product in products)
    return total_price

# Function to validate user input
def validate_user_input(order_data: OrderCreate):
    # Logic to validate user input
    pass

# Class to handle email sending
class EmailSender:
    def __init__(self):
        # Initialize email sender
        pass
    
    def send_email(self, email: str, subject: str, message: str):
        # Logic to send email
        print(f"Sending email to {email} with subject '{subject}' and message '{message}'")

# Define Dramatiq actors for background tasks
@dramatiq.actor
def send_confirmation_email(order_id: int, email: str, email_sender: EmailSender):
    time.sleep(5)  # Simulate email sending delay
    # Logic to send confirmation email
    email_sender.send_email(email=email, subject="Order Confirmation", message=f"Your order with ID {order_id} has been confirmed.")

@dramatiq.actor
def process_payment(order_id: int):
    time.sleep(10)  # Simulate payment processing delay
    # Logic to process payment
    print(f"Payment processed for order {order_id}")

# Kafka producer initialization
producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVER,
                         value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# Kafka consumer initialization
consumer = KafkaConsumer(KAFKA_TOPIC,
                         bootstrap_servers=KAFKA_BOOTSTRAP_SERVER,
                         auto_offset_reset='earliest',
                         enable_auto_commit=True,
                         group_id='my-group')

# Endpoint to create an order
def get_products(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    return products

@app.post("/orders/")
def create_order(
    background_tasks: BackgroundTasks,
    order_data: OrderCreate,
    products: List[Product] = Depends(get_products),
    db: Session = Depends(get_db),
    email_sender: EmailSender = Depends()
):
    # Validate user input
    validate_user_input(order_data)

    # Calculate total price
    total_price = calculate_total_price(order_data, products)

    # Save order to database
    db_order = Order(**order_data.dict(), total_price=total_price)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    # Send confirmation email asynchronously
    background_tasks.add_task(send_confirmation_email, db_order.id, order_data.email, email_sender)
    # Process payment asynchronously
    background_tasks.add_task(process_payment, db_order.id)
    
    # Log order creation event to Kafka
    log_data = {'event': 'order_created', 'order_id': db_order.id}
    producer.send(KAFKA_TOPIC, value=log_data)
    
    return db_order

@app.get("/users/", response_model=List[User])
def get_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return db.query(User).offset(skip).limit(limit).all()

@app.post("/users/", response_model=User)
def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    db_user = User(**user_data.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.put("/users/{user_id}", response_model=User)
def update_user(user_id: int, user_data: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    for key, value in user_data.dict().items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return {"message": "User deleted successfully"}

# Kafka consumer to log events
@app.on_event("startup")
def start_kafka_consumer():
    def consume():
        for message in consumer:
            log_data = json.loads(message.value.decode('utf-8'))
            print("Received log:", log_data)
    import threading
    threading.Thread(target=consume).start()

# Similar endpoints for other CRUD operations

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
