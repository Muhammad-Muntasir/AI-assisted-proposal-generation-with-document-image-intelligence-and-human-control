/**
 * AuthGuard.tsx
 * -------------
 * Route protection component.
 *
 * Wraps any page that requires authentication.
 * If the user is NOT logged in → redirects to the login page (/).
 * If the user IS logged in → renders the protected page normally.
 *
 * Usage in App.tsx:
 *   <AuthGuard><Dashboard /></AuthGuard>
 */
import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { isAuthenticated } from '../auth'

interface AuthGuardProps {
  children: ReactNode // The protected page/component to render
}

export default function AuthGuard({ children }: AuthGuardProps) {
  // If not authenticated, redirect to login page
  if (!isAuthenticated()) {
    return <Navigate to="/" replace />
  }

  // User is authenticated — render the protected content
  return <>{children}</>
}
