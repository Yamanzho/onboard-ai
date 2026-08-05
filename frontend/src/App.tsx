import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './hooks/useAuth'
import { SuperAdminAuthProvider } from './hooks/useSuperAdminAuth'
import { AppRoutes } from './routes/AppRoutes'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SuperAdminAuthProvider>
          <AppRoutes />
        </SuperAdminAuthProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
