// // app/utils/firebase.ts
// import { initializeApp, FirebaseApp, getApps } from "firebase/app";
// import { getAuth, Auth } from "firebase/auth";

// // 1. Define Firebase Configuration Type
// interface FirebaseConfig {
//   apiKey: string;
//   authDomain: string;
//   projectId: string;
//   storageBucket: string;
//   messagingSenderId: string;
//   appId: string;
// }

// // 2. Load Firebase Configuration from Environment Variables
// const firebaseConfig: FirebaseConfig = {
//   apiKey: process.env.FIREBASE_API_KEY || "",
//   authDomain: process.env.FIREBASE_AUTH_DOMAIN || "",
//   projectId: process.env.FIREBASE_PROJECT_ID || "",
//   storageBucket: process.env.FIREBASE_STORAGE_BUCKET || "",
//   messagingSenderId: process.env.FIREBASE_MESSAGING_SENDER_ID || "",
//   appId: process.env.FIREBASE_APP_ID || "",
// };

// // 3. Initialize Firebase App (Singleton Pattern)
// let firebaseApp: FirebaseApp;

// if (!getApps().length) {
//   firebaseApp = initializeApp(firebaseConfig);
// } else {
//   firebaseApp = getApps()[0]; // Use existing app if already initialized
// }

// // 4. Get Firebase Auth Instance
// let firebaseAuth: Auth;

// if (firebaseApp) {
//   firebaseAuth = getAuth(firebaseApp);
// }

// // 5. (Optional) Helper Functions (Examples)
// // These are examples - adapt to your specific needs
// async function getCurrentUserToken(): Promise<string | null> {
//   try {
//     const user = firebaseAuth.currentUser;
//     if (user) {
//       return await user.getIdToken();
//     }
//     return null;
//   } catch (error) {
//     console.error("Error getting current user token:", error);
//     return null;
//   }
// }

// // Example: Function to sign out
// async function signOutFirebase(): Promise<void> {
//   try {
//     await firebaseAuth.signOut();
//   } catch (error) {
//     console.error("Error signing out:", error);
//   }
// }

// // 6. Export Firebase Instances and Helper Functions
// export { firebaseApp, firebaseAuth, firebaseConfig, getCurrentUserToken, signOutFirebase };