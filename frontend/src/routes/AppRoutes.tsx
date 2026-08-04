import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '../layouts/AppLayout'
import { AuthLayout } from '../layouts/AuthLayout'
import { DashboardPage } from '../pages/DashboardPage'
import { LoginPage } from '../pages/LoginPage'
import { ArticleCreatePage } from '../pages/knowledge/ArticleCreatePage'
import { ArticleEditPage } from '../pages/knowledge/ArticleEditPage'
import { ArticleListPage } from '../pages/knowledge/ArticleListPage'
import { CategoriesPage } from '../pages/knowledge/CategoriesPage'
import { TagsPage } from '../pages/knowledge/TagsPage'
import { EmployeesPage } from '../pages/stubs/EmployeesPage'
import { OnboardingPage } from '../pages/stubs/OnboardingPage'
import { SettingsPage } from '../pages/stubs/SettingsPage'
import { ProtectedRoute } from './ProtectedRoute'

export function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/knowledge/articles" element={<ArticleListPage />} />
            <Route path="/knowledge/articles/new" element={<ArticleCreatePage />} />
            <Route path="/knowledge/articles/:articleId" element={<ArticleEditPage />} />
            <Route path="/knowledge/categories" element={<CategoriesPage />} />
            <Route path="/knowledge/tags" element={<TagsPage />} />
            <Route path="/employees" element={<EmployeesPage />} />
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
