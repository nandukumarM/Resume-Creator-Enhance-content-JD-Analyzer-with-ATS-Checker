import os
import unittest
import json
import sqlite3
from app import app, get_db_connection, init_db, load_users, save_users, load_admins, save_admins, load_history, save_history, add_history_entry, load_feedbacks

class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_database_initialization(self):
        """Test if database tables are created correctly"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check users table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        self.assertIsNotNone(cursor.fetchone(), "users table should exist")
        
        # Check admins table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'")
        self.assertIsNotNone(cursor.fetchone(), "admins table should exist")
        
        # Check history table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='history'")
        self.assertIsNotNone(cursor.fetchone(), "history table should exist")
        
        # Check feedback table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
        self.assertIsNotNone(cursor.fetchone(), "feedback table should exist")
        
        conn.close()

    def test_users_crud(self):
        """Test saving and loading users in SQLite"""
        test_username = "testuser_db_verification"
        test_data = {
            'username': test_username,
            'email': 'testuser@example.com',
            'password': 'test_password_hash',
            'user_id': 'test-uuid-1234',
            'created_at': '2026-05-31 12:00:00'
        }
        
        # Load and verify it's clean (or not)
        users = load_users()
        users[test_username] = test_data
        save_users(users)
        
        # Reload
        users_reloaded = load_users()
        self.assertIn(test_username, users_reloaded)
        self.assertEqual(users_reloaded[test_username]['email'], test_data['email'])
        self.assertEqual(users_reloaded[test_username]['user_id'], test_data['user_id'])

    def test_admins_crud(self):
        """Test saving and loading admins in SQLite"""
        test_admin = "testadmin_db_verification"
        test_data = {
            'username': test_admin,
            'email': 'admin@example.com',
            'password': 'admin_password_hash',
            'admin_id': 'admin-uuid-5678',
            'created_at': '2026-05-31 12:00:00'
        }
        
        admins = load_admins()
        admins[test_admin] = test_data
        save_admins(admins)
        
        admins_reloaded = load_admins()
        self.assertIn(test_admin, admins_reloaded)
        self.assertEqual(admins_reloaded[test_admin]['email'], test_data['email'])

    def test_history_and_feedback(self):
        """Test history entries and feedback submissions"""
        # Test adding history entry
        test_user_id = 'test-uuid-1234'
        add_history_entry(test_user_id, 'resume', 'test_resume.pdf', 'Test Developer Resume')
        
        history = load_history()
        user_history = [h for h in history if h['user_id'] == test_user_id]
        self.assertTrue(len(user_history) > 0)
        self.assertEqual(user_history[0]['title'], 'Test Developer Resume')
        
        # Test submitting feedback via endpoint
        feedback_payload = {
            'rating': 5,
            'comment': 'Exceptional tool! Extremely helpful.',
            'page': '/dashboard'
        }
        response = self.client.post('/feedback', 
                                    data=json.dumps(feedback_payload),
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify feedback in database
        feedbacks = load_feedbacks()
        matching_feedbacks = [f for f in feedbacks if f['comment'] == feedback_payload['comment']]
        self.assertTrue(len(matching_feedbacks) > 0)
        self.assertEqual(matching_feedbacks[0]['rating'], 5)

if __name__ == '__main__':
    unittest.main()
