import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '../layouts/AppLayout'
import { AuthLayout } from '../layouts/AuthLayout'
import { SuperAdminAuthLayout } from '../layouts/SuperAdminAuthLayout'
import { SuperAdminLayout } from '../layouts/SuperAdminLayout'
import { DashboardPage } from '../pages/DashboardPage'
import { LoginPage } from '../pages/LoginPage'
import { AssignmentCreatePage } from '../pages/assignments/AssignmentCreatePage'
import { AssignmentDetailPage } from '../pages/assignments/AssignmentDetailPage'
import { AssignmentListPage } from '../pages/assignments/AssignmentListPage'
import { EmployeeCreatePage } from '../pages/employees/EmployeeCreatePage'
import { EmployeeDetailPage } from '../pages/employees/EmployeeDetailPage'
import { EmployeeEditPage } from '../pages/employees/EmployeeEditPage'
import { EmployeeListPage } from '../pages/employees/EmployeeListPage'
import { ArticleCreatePage } from '../pages/knowledge/ArticleCreatePage'
import { ArticleEditPage } from '../pages/knowledge/ArticleEditPage'
import { ArticleListPage } from '../pages/knowledge/ArticleListPage'
import { CategoriesPage } from '../pages/knowledge/CategoriesPage'
import { TagsPage } from '../pages/knowledge/TagsPage'
import { ProgramCreatePage } from '../pages/onboarding/ProgramCreatePage'
import { ProgramDetailPage } from '../pages/onboarding/ProgramDetailPage'
import { ProgramEditPage } from '../pages/onboarding/ProgramEditPage'
import { ProgramListPage } from '../pages/onboarding/ProgramListPage'
import { SettingsPage } from '../pages/SettingsPage'
import { CompanySettingsPage } from '../pages/CompanySettingsPage'
import { ResetPasswordPage } from '../pages/ResetPasswordPage'
import { MyOnboardingPage } from '../pages/employee/MyOnboardingPage'
import { MyActivePage } from '../pages/employee/MyActivePage'
import { MyHistoryPage } from '../pages/employee/MyHistoryPage'
import { MyCalendarPage } from '../pages/employee/MyCalendarPage'
import { MyCompanyPage } from '../pages/employee/MyCompanyPage'
import { SuperAdminCompanyCreatePage } from '../pages/super-admin/SuperAdminCompanyCreatePage'
import { SuperAdminCompanyDetailPage } from '../pages/super-admin/SuperAdminCompanyDetailPage'
import { SuperAdminCompanyEditPage } from '../pages/super-admin/SuperAdminCompanyEditPage'
import { SuperAdminCompanyListPage } from '../pages/super-admin/SuperAdminCompanyListPage'
import { SuperAdminDashboardPage } from '../pages/super-admin/SuperAdminDashboardPage'
import { SuperAdminLoginPage } from '../pages/super-admin/SuperAdminLoginPage'
import { InviteAcceptPage } from '../pages/InviteAcceptPage'
import { SuperAdminAuditLogPage } from '../pages/super-admin/SuperAdminAuditLogPage'
import { SuperAdminSettingsPage } from '../pages/super-admin/SuperAdminSettingsPage'
import { SuperAdminSubscriptionsPage } from '../pages/super-admin/SuperAdminSubscriptionsPage'
import { SuperAdminUsersPage } from '../pages/super-admin/SuperAdminUsersPage'
import { ProtectedRoute } from './ProtectedRoute'
import { RequireRole } from './RequireRole'
import { SuperAdminProtectedRoute } from './SuperAdminProtectedRoute'
import { RoleHomeRedirect } from './RoleHomeRedirect'

export function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        <Route path="/invite" element={<InviteAcceptPage />} />
        {/* Legacy path links from older emails; prefer /invite#<token>.
            Keep until INVITE_TTL_HOURS (default 24h) after last path-link send. */}
        <Route path="/invite/:token" element={<InviteAcceptPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/reset-password/:token" element={<ResetPasswordPage />} />

        <Route element={<SuperAdminAuthLayout />}>
          <Route path="/super-admin/login" element={<SuperAdminLoginPage />} />
        </Route>

        <Route element={<SuperAdminProtectedRoute />}>
          <Route path="/super-admin" element={<SuperAdminLayout />}>
            <Route
              index
              element={<Navigate to="/super-admin/dashboard" replace />}
            />
            <Route path="dashboard" element={<SuperAdminDashboardPage />} />
            <Route path="companies" element={<SuperAdminCompanyListPage />} />
            <Route
              path="companies/new"
              element={<SuperAdminCompanyCreatePage />}
            />
            <Route
              path="companies/:companyId"
              element={<SuperAdminCompanyDetailPage />}
            />
            <Route
              path="companies/:companyId/edit"
              element={<SuperAdminCompanyEditPage />}
            />
            <Route path="users" element={<SuperAdminUsersPage />} />
            <Route
              path="subscriptions"
              element={<SuperAdminSubscriptionsPage />}
            />
            <Route path="audit-log" element={<SuperAdminAuditLogPage />} />
            <Route path="settings" element={<SuperAdminSettingsPage />} />
          </Route>
        </Route>

        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<RoleHomeRedirect />} />

            <Route element={<RequireRole allowed={['admin', 'hr']} />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/knowledge/articles" element={<ArticleListPage />} />
              <Route
                path="/knowledge/articles/new"
                element={<ArticleCreatePage />}
              />
              <Route
                path="/knowledge/articles/:articleId"
                element={<ArticleEditPage />}
              />
              <Route path="/knowledge/categories" element={<CategoriesPage />} />
              <Route path="/knowledge/tags" element={<TagsPage />} />
              <Route path="/employees" element={<EmployeeListPage />} />
              <Route path="/employees/new" element={<EmployeeCreatePage />} />
              <Route
                path="/employees/:employeeId"
                element={<EmployeeDetailPage />}
              />
              <Route
                path="/employees/:employeeId/edit"
                element={<EmployeeEditPage />}
              />
              <Route path="/onboarding" element={<ProgramListPage />} />
              <Route path="/onboarding/new" element={<ProgramCreatePage />} />
              <Route
                path="/onboarding/:programId"
                element={<ProgramDetailPage />}
              />
              <Route
                path="/onboarding/:programId/edit"
                element={<ProgramEditPage />}
              />
              <Route path="/assignments" element={<AssignmentListPage />} />
              <Route path="/assignments/new" element={<AssignmentCreatePage />} />
              <Route
                path="/assignments/:assignmentId"
                element={<AssignmentDetailPage />}
              />
            </Route>

            <Route element={<RequireRole allowed={['admin']} />}>
              <Route
                path="/company-settings"
                element={<CompanySettingsPage />}
              />
            </Route>

            <Route element={<RequireRole allowed={['employee']} />}>
              <Route path="/my-onboarding" element={<MyOnboardingPage />} />
              <Route path="/my/active" element={<MyActivePage />} />
              <Route path="/my/history" element={<MyHistoryPage />} />
              <Route path="/my/calendar" element={<MyCalendarPage />} />
              <Route path="/my/company" element={<MyCompanyPage />} />
            </Route>

            <Route element={<RequireRole allowed={['admin', 'hr', 'employee']} />}>
              <Route
                path="/profile"
                element={<SettingsPage section="profile" />}
              />
              <Route
                path="/security"
                element={<SettingsPage section="security" />}
              />
              <Route
                path="/settings"
                element={<Navigate to="/profile" replace />}
              />
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<RoleHomeRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
