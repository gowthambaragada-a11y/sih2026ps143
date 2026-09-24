/**
 * Firebase Auth + Storage service.
 *
 * Initialised from VITE_FIREBASE_* env vars. If the variables are absent
 * (local/demo build), all auth/storage helpers are stubbed: onAuthChange
 * immediately reports a signed-out user and uploads fall back to a
 * "demo" result, so the full journey still works in Guest / Evaluator mode.
 */
import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  GoogleAuthProvider,
  type User,
} from "firebase/auth";
import {
  deleteObject,
  getDownloadURL,
  getStorage,
  listAll,
  ref,
  uploadBytesResumable,
} from "firebase/storage";
import type { StoredImage } from "../types";

const CFG = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const isFirebaseConfigured = Boolean(
  CFG.apiKey && CFG.authDomain && CFG.projectId && CFG.storageBucket,
);

let app: FirebaseApp | null = null;

function getApp(): FirebaseApp {
  if (!isFirebaseConfigured) {
    throw new Error("Firebase is not configured — add VITE_FIREBASE_* env vars.");
  }
  if (!app) app = initializeApp(CFG);
  return app;
}

export interface AuthUser {
  uid: string;
  name: string;
  email: string | null;
  photoURL: string | null;
  isGuest: boolean;
}

function toAuthUser(u: User | null): AuthUser | null {
  if (!u) return null;
  return {
    uid: u.uid,
    name: u.displayName ?? u.email?.split("@")[0] ?? "User",
    email: u.email,
    photoURL: u.photoURL,
    isGuest: false,
  };
}

/* ---------------- Auth helpers ---------------- */

export async function loginUser(email: string, password: string): Promise<AuthUser> {
  if (!isFirebaseConfigured) throw new Error("Firebase is not configured for this build.");
  const cred = await signInWithEmailAndPassword(getAuth(getApp()), email, password);
  return toAuthUser(cred.user)!;
}

export async function loginWithGoogle(): Promise<AuthUser> {
  if (!isFirebaseConfigured) throw new Error("Firebase is not configured for this build.");
  const provider = new GoogleAuthProvider();
  const cred = await signInWithPopup(getAuth(getApp()), provider);
  return toAuthUser(cred.user)!;
}

export async function logoutUser(): Promise<void> {
  if (!isFirebaseConfigured) return;
  await signOut(getAuth(getApp()));
}

/** Subscribe to auth state. Returns an unsubscribe function. Never throws. */
export function onAuthChange(cb: (user: AuthUser | null) => void): () => void {
  if (!isFirebaseConfigured) {
    cb(null);
    return () => {};
  }
  return onAuthStateChanged(getAuth(getApp()), (u) => cb(toAuthUser(u)));
}

/* ---------------- Storage helpers ---------------- */

export interface UploadTarget {
  image: StoredImage;
  isLive: boolean;
}

/** Upload a file to firebase storage under `uploads/{uid}/{file_id}`. */
export async function uploadImageToFirebase(
  file: File,
  uid: string,
  onProgress?: (pct: number) => void,
): Promise<UploadTarget> {
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  if (!isFirebaseConfigured) {
    // Demo fallback: object URL, nothing persisted.
    const url = URL.createObjectURL(file);
    const img = await readDims(file);
    return {
      isLive: false,
      image: {
        id,
        name: file.name,
        size: file.size,
        type: file.type || "image/*",
        url,
        storagePath: `demo:${file.name}`,
        uploadedAt: Date.now(),
        progress: 100,
        width: img?.width,
        height: img?.height,
      },
    };
  }

  const storage = getStorage(getApp());
  const path = `uploads/${uid}/${id}-${file.name.replace(/[^a-zA-Z0-9._-]/g, "_")}`;
  const storageRef = ref(storage, path);
  const task = uploadBytesResumable(storageRef, file);
  const result = await new Promise<{ path: string; url: string }>((resolve, reject) => {
    task.on(
      "state_changed",
      (snap) => {
        const pct = Math.round((snap.bytesTransferred / snap.totalBytes) * 100);
        onProgress?.(pct);
      },
      (err) => reject(err),
      () => {
        void getDownloadURL(task.snapshot.ref).then((url) => resolve({ path, url }));
      },
    );
  });
  const img = await readDims(file);
  return {
    isLive: true,
    image: {
      id,
      name: file.name,
      size: file.size,
      type: file.type || "image/*",
      url: result.url,
      storagePath: result.path,
      uploadedAt: Date.now(),
      progress: 100,
      width: img?.width,
      height: img?.height,
    },
  };
}

/** List previously uploaded images for a user. */
export async function fetchUserUploads(uid: string): Promise<StoredImage[]> {
  if (!isFirebaseConfigured) return [];
  const storage = getStorage(getApp());
  const list = await listAll(ref(storage, `uploads/${uid}`));
  const items = await Promise.all(
    list.items.map(async (item) => {
      const url = await getDownloadURL(item);
      return {
        id: item.name,
        name: item.name,
        size: 0,
        type: "image/*",
        url,
        storagePath: item.fullPath,
        uploadedAt: Date.now(),
        progress: 100,
      } satisfies StoredImage;
    }),
  );
  return items;
}

/** Delete an image; resolves silently in demo mode. */
export async function deleteImageFromFirebase(storagePath: string): Promise<void> {
  if (!isFirebaseConfigured || storagePath.startsWith("demo:")) return;
  const storage = getStorage(getApp());
  await deleteObject(ref(storage, storagePath));
}

async function readDims(
  file: File,
): Promise<{ width?: number; height?: number } | null> {
  try {
    const url = URL.createObjectURL(file);
    const img = new Image();
    const dims = await new Promise<{ width: number; height: number }>((resolve, reject) => {
      img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = () => reject(new Error("load failed"));
      img.src = url;
    });
    URL.revokeObjectURL(url);
    return dims;
  } catch {
    return null;
  }
}