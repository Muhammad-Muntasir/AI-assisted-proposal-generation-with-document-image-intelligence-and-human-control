/**
 * auth.ts
 * -------
 * Authentication utilities using AWS Cognito.
 *
 * What it does:
 *   - Connects to the AWS Cognito User Pool configured in .env
 *   - Provides login, sign up, email verification, and logout functions
 *   - Tracks login state in localStorage (key: 'isAuthenticated')
 *
 * Environment variables required (.env):
 *   VITE_COGNITO_USER_POOL_ID  — Cognito User Pool ID
 *   VITE_COGNITO_CLIENT_ID     — Cognito App Client ID
 */
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
} from 'amazon-cognito-identity-js'

// Connect to the Cognito User Pool using env variables
const poolData = {
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID ?? '',
  ClientId:   import.meta.env.VITE_COGNITO_CLIENT_ID ?? '',
}
const userPool = new CognitoUserPool(poolData)

// Key used to store auth state in localStorage
const AUTH_KEY = 'isAuthenticated'

/** Check if the user is currently logged in */
export function isAuthenticated(): boolean {
  return localStorage.getItem(AUTH_KEY) === 'true'
}

/** Clear auth state and sign out from Cognito */
export function clearAuth(): void {
  localStorage.removeItem(AUTH_KEY)
  const user = userPool.getCurrentUser()
  if (user) user.signOut()
}

/** Set or clear the authenticated state in localStorage */
export function setAuthenticated(value: boolean): void {
  if (value) {
    localStorage.setItem(AUTH_KEY, 'true')
  } else {
    clearAuth()
  }
}

/**
 * Log in with email and password via Cognito.
 * On success: sets isAuthenticated = true in localStorage.
 * On failure: throws an error with a user-friendly message.
 */
export function cognitoLogin(email: string, password: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const authDetails = new AuthenticationDetails({ Username: email, Password: password })
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })

    cognitoUser.authenticateUser(authDetails, {
      onSuccess: () => {
        setAuthenticated(true)
        resolve()
      },
      onFailure: (err) => {
        reject(new Error(err.message || 'Login failed'))
      },
      newPasswordRequired: () => {
        // User must reset their password (set by admin)
        reject(new Error('Password reset required. Please contact your administrator.'))
      },
    })
  })
}

/**
 * Register a new user with email and password.
 * After sign up, the user must verify their email with a code.
 */
export function cognitoSignUp(email: string, password: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const attributes = [new CognitoUserAttribute({ Name: 'email', Value: email })]
    userPool.signUp(email, password, attributes, [], (err) => {
      if (err) reject(new Error(err.message || 'Sign up failed'))
      else resolve()
    })
  })
}

/** Get the currently logged-in user's email from Cognito session */
export function getCurrentUserEmail(): string {
  const user = userPool.getCurrentUser()
  return user?.getUsername() ?? ''
}

export function cognitoConfirmSignUp(email: string, code: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
    cognitoUser.confirmRegistration(code, true, (err) => {
      if (err) reject(new Error(err.message || 'Confirmation failed'))
      else resolve()
    })
  })
}
