TULAY – Community Help & Volunteer System (Enhanced)
=====================================================

HOW TO RUN
----------
1. Install dependencies:
   pip install flask authlib requests

2. Set environment variables for OAuth (see OAUTH SETUP below):
   export GOOGLE_CLIENT_ID="your-client-id"
   export GOOGLE_CLIENT_SECRET="your-client-secret"
   export FACEBOOK_APP_ID="your-app-id"
   export FACEBOOK_APP_SECRET="your-app-secret"
   export TULAY_SECRET="a-long-random-secret-key"

3. Run the app:
   python app.py

4. Open http://localhost:5000 in your browser.


OAUTH SETUP
-----------

▶ GOOGLE LOGIN
  1. Go to https://console.cloud.google.com/
  2. Create a project → APIs & Services → Credentials
  3. Create OAuth 2.0 Client ID (Web application)
  4. Add Authorized redirect URI: http://localhost:5000/auth/google/callback
     (For production: https://yourdomain.com/auth/google/callback)
  5. Copy the Client ID and Client Secret into the env vars above.
  6. Enable "Google+ API" or "People API" in the API library.

▶ FACEBOOK LOGIN
  1. Go to https://developers.facebook.com/
  2. Create an App → Consumer type
  3. Add "Facebook Login" product
  4. In Facebook Login → Settings, add Valid OAuth Redirect URIs:
     http://localhost:5000/auth/facebook/callback
  5. Copy App ID and App Secret into the env vars above.
  6. In App Settings → Basic, add your Privacy Policy URL and App Domain.

⚠️  NOTE: Facebook login requires HTTPS in production.
    For local testing, use the Facebook Test Users feature
    or switch to "Development" mode in the Facebook App Dashboard.


WHAT'S NEW IN THIS VERSION
---------------------------
✅ Google Sign-In (OAuth 2.0 via Authlib)
✅ Facebook Login (OAuth 2.0 via Authlib)
✅ New-user role selection screen after social login
✅ Demo accounts REMOVED — real accounts only
✅ Animated login background with orbs and particles
✅ Volunteer notifications when a new request is submitted
✅ Profile photo upload for all users
✅ Enhanced map with OSRM routing (fastest route)
✅ Step-by-step directions panel
✅ "Open in Google Maps" button
✅ Live proximity banner while navigating
✅ Modern Nunito typography throughout
✅ Green gradient top bar + polished card design

DEMO LOGINS (email/password fallback — create your own accounts)
----------------------------------------------------------------
No demo accounts ship with this version.
Create a real account via Google, Facebook, or email registration.

