from uuid import UUID
from flask import jsonify
from flask_restx import Namespace, Resource, fields
from werkzeug.exceptions import HTTPException

from app.worker.tasks import process_book, get_book_status

api = Namespace('books', description='Book processing operations')

# Define response model
process_response = api.model('ProcessResponse', {
    'task_id': fields.String(required=True, description='Task ID'),
    'book_id': fields.String(required=True, description='Book ID'),
    'status': fields.String(required=True, description='Processing status'),
    'message': fields.String(required=True, description='Status message')
})

@api.route('/<uuid:book_id>/process')
class BookProcess(Resource):
    @api.response(202, 'Processing started', process_response)
    @api.response(500, 'Internal server error')
    def post(self, book_id):
        """Start the book processing task"""
        try:
            task = process_book.delay(str(book_id))
            
            return {
                "task_id": str(task.id),
                "book_id": str(book_id),
                "status": "processing",
                "message": "Book processing started"
            }, 202
        except Exception as e:
            api.abort(500, str(e))

@api.route('/<uuid:book_id>/status')
class BookStatus(Resource):
    @api.response(200, 'Success', process_response)
    @api.response(500, 'Internal server error')
    def get(self, book_id):
        """Get the status of a book processing task"""
        try:
            task = get_book_status.delay(str(book_id))
            result = task.get()  # Wait for the result
            
            return {
                "task_id": str(task.id),
                "book_id": str(book_id),
                "status": result["status"],
                "message": result["message"]
            }, 200
        except Exception as e:
            api.abort(500, str(e))