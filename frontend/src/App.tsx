/**
 * App.tsx
 * -------
 * Root component — defines all application routes.
 *
 * Routes:
 *   /           → Login page (public)
 *   /dashboard  → Main dashboard (protected by AuthGuard)
 *
 * AuthGuard checks if the user is logged in before allowing
 * access to the dashboard. If not logged in, redirects to /.
 */
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import AuthGuard from './components/AuthGuard'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public route — anyone can access the login page */}
        <Route path="/" element={<Login />} />

        {/* Protected route — only accessible when logged in */}
        <Route
          path="/dashboard"
          element={
            <AuthGuard>
              <Dashboard />
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
