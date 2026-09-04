import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthLayout } from '../layouts/AuthLayout'
import { CompanyAdminLayout } from '../layouts/CompanyAdminLayout'
import { EmployeeLayout } from '../layouts/EmployeeLayout'
import { HrLayout } from '../layouts/HrLayout'
import { PlatformAdminLayout } from '../layouts/PlatformAdminLayout'
import { SuperAdminAuthLayout } from '../layouts/SuperAdminAuthLayout'
import { DashboardPage } from '../pages/DashboardPage'
import { LoginPage } from '../pages/LoginPage'
import { LoginChoicePage } from '../pages/LoginChoicePage'
import { AssignmentCreatePage } from '../pages/assignments/AssignmentCreatePage'
import { AssignmentDetailPage } from '../pages/assignments/AssignmentDetailPage'
import { AssignmentListPage } from '../pages/assignments/AssignmentListPage'
import { CompanyDashboardPage } from '../pages/company/CompanyDashboardPage'
import { HrDashboardPage } from '../pages/hr/HrDashboardPage'
import { HrCreatePage } from '../pages/company/HrCreatePage'
import { HrListPage } from '../pages/company/HrListPage'
import { EmployeeCreatePage } from '../pages/employees/EmployeeCreatePage'
import { EmployeeDetailPage } from '../pages/employees/EmployeeDetailPage'
import { EmployeeEditPage } from '../pages/employees/EmployeeEditPage'
import { EmployeeListPage } from '../pages/employees/EmployeeListPage'
import { ArticleCreatePage } from '../pages/knowledge/ArticleCreatePage'
import { ArticleEditPage } from '../pages/knowledge/ArticleEditPage'
import { ArticleListPage } from '../pages/knowledge/ArticleListPage'
import { DepartmentListPage } from '../pages/org/DepartmentListPage'
import { TopicListPage } from '../pages/org/TopicListPage'
import { CategoriesPage } from '../pages/knowledge/CategoriesPage'
import { TagsPage } from '../pages/knowledge/TagsPage'
import { ProgramCreatePage } from '../pages/onboarding/ProgramCreatePage'
import { ProgramDetailPage } from '../pages/onboarding/ProgramDetailPage'
import { ProgramEditPage } from '../pages/onboarding/ProgramEditPage'
import { ProgramListPage } from '../pages/onboarding/ProgramListPage'
import { SettingsPage } from '../pages/SettingsPage'
import { CompanySettingsPage } from '../pages/CompanySettingsPage'
import { ResetPasswordPage } from '../pages/ResetPasswordPage'
import { EmployeeDashboardPage } from '../pages/employee/EmployeeDashboardPage'
import { MyOnboardingPage } from '../pages/employee/MyOnboardingPage'
import { MyActivePage } from '../pages/employee/MyActivePage'
import { MyHistoryPage } from '../pages/employee/MyHistoryPage'
import { MyCalendarPage } from '../pages/employee/MyCalendarPage'
import { MyCompanyPage } from '../pages/employee/MyCompanyPage'
import { EmployeeKnowledgeListPage } from '../pages/employee/EmployeeKnowledgeListPage'
import { EmployeeArticlePage } from '../pages/employee/EmployeeArticlePage'
import { EmployeeAIPage } from '../pages/employee/EmployeeAIPage'
import { CompanyAuditLogPage } from '../pages/audit/CompanyAuditLogPage'
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
import { RequireWorkspace } from './RequireWorkspace'
import { RoleHomeRedirect } from './RoleHomeRedirect'
import { SuperAdminProtectedRoute } from './SuperAdminProtectedRoute'

/** Must be a plain function (not a component) so RR sees Route children. */
function managementRoutes(opts: {
  excludeHrFromEmployees?: boolean
  includeHrMgmt?: boolean
  employeesOnly?: boolean
}) {
  const employeeList = opts.employeesOnly ? (
    <EmployeeListPage includeRoles={['employee']} />
  ) : opts.excludeHrFromEmployees ? (
    <EmployeeListPage excludeRoles={['hr']} />
  ) : (
    <EmployeeListPage />
  )

  return (
    <>
      <Route path="employees" element={employeeList} />
      <Route path="employees/new" element={<EmployeeCreatePage />} />
      <Route path="employees/:employeeId" element={<EmployeeDetailPage />} />
      <Route path="employees/:employeeId/edit" element={<EmployeeEditPage />} />

      <Route path="departments" element={<DepartmentListPage />} />
      <Route path="topics" element={<TopicListPage />} />

      {opts.includeHrMgmt ? (
        <>
          <Route path="hr" element={<HrListPage />} />
          <Route path="hr/create" element={<HrCreatePage />} />
          <Route path="hr/:employeeId" element={<EmployeeDetailPage />} />
          <Route path="hr/:employeeId/edit" element={<EmployeeEditPage />} />
        </>
      ) : null}

      <Route path="onboarding" element={<ProgramListPage />} />
      <Route path="onboarding/new" element={<ProgramCreatePage />} />
      <Route path="onboarding/:programId" element={<ProgramDetailPage />} />
      <Route path="onboarding/:programId/edit" element={<ProgramEditPage />} />

      <Route path="assignments" element={<AssignmentListPage />} />
      <Route path="assignments/new" element={<AssignmentCreatePage />} />
      <Route
        path="assignments/:assignmentId"
        element={<AssignmentDetailPage />}
      />

      <Route path="knowledge" element={<ArticleListPage />} />
      <Route path="knowledge/new" element={<ArticleCreatePage />} />
      <Route path="knowledge/categories" element={<CategoriesPage />} />
      <Route path="knowledge/tags" element={<TagsPage />} />
      <Route path="knowledge/:articleId" element={<ArticleEditPage />} />

      <Route path="progress" element={<DashboardPage />} />
      <Route path="audit" element={<CompanyAuditLogPage />} />

      <Route path="profile" element={<SettingsPage section="profile" />} />
      <Route path="security" element={<SettingsPage section="security" />} />
    </>
  )
}

export function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AuthLayout />}>
          <Route index element={<LoginChoicePage />} />
          <Route path="/admin/login" element={<LoginPage expectedRole="admin" />} />
          <Route path="/hr/login" element={<LoginPage expectedRole="hr" />} />
          <Route
            path="/employee/login"
            element={<LoginPage expectedRole="employee" />}
          />
        </Route>

        <Route path="/invite" element={<InviteAcceptPage />} />
        <Route path="/invite/:token" element={<InviteAcceptPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/reset-password/:token" element={<ResetPasswordPage />} />

        <Route element={<SuperAdminAuthLayout />}>
          <Route path="/super-admin/login" element={<SuperAdminLoginPage />} />
        </Route>

        <Route element={<SuperAdminProtectedRoute />}>
          <Route element={<RequireWorkspace workspace="platform" />}>
            <Route path="/platform" element={<PlatformAdminLayout />}>
              <Route index element={<SuperAdminDashboardPage />} />
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
              <Route path="audit" element={<SuperAdminAuditLogPage />} />
              <Route path="settings" element={<SuperAdminSettingsPage />} />
            </Route>
          </Route>
        </Route>

        <Route path="/super-admin" element={<Navigate to="/platform" replace />} />
        <Route
          path="/super-admin/dashboard"
          element={<Navigate to="/platform" replace />}
        />
        <Route
          path="/super-admin/companies/*"
          element={<Navigate to="/platform/companies" replace />}
        />
        <Route
          path="/super-admin/users"
          element={<Navigate to="/platform/users" replace />}
        />
        <Route
          path="/super-admin/subscriptions"
          element={<Navigate to="/platform/subscriptions" replace />}
        />
        <Route
          path="/super-admin/audit-log"
          element={<Navigate to="/platform/audit" replace />}
        />
        <Route
          path="/super-admin/settings"
          element={<Navigate to="/platform/settings" replace />}
        />

        <Route element={<ProtectedRoute />}>
          <Route element={<RequireWorkspace workspace="company" />}>
            <Route path="/company" element={<CompanyAdminLayout />}>
              <Route index element={<CompanyDashboardPage />} />
              <Route element={<RequireRole allowed={['admin']} />}>
                {managementRoutes({
                  excludeHrFromEmployees: true,
                  includeHrMgmt: true,
                })}
                <Route path="settings" element={<CompanySettingsPage />} />
              </Route>
            </Route>
          </Route>

          <Route element={<RequireWorkspace workspace="hr" />}>
            <Route path="/hr" element={<HrLayout />}>
              <Route index element={<HrDashboardPage />} />
              <Route element={<RequireRole allowed={['hr']} />}>
                {managementRoutes({ employeesOnly: true })}
              </Route>
            </Route>
          </Route>

          <Route element={<RequireWorkspace workspace="employee" />}>
            <Route path="/employee" element={<EmployeeLayout />}>
              <Route index element={<EmployeeDashboardPage />} />
              <Route element={<RequireRole allowed={['employee']} />}>
                <Route path="onboarding" element={<MyOnboardingPage />} />
                <Route path="active" element={<MyActivePage />} />
                <Route path="history" element={<MyHistoryPage />} />
                <Route path="calendar" element={<MyCalendarPage />} />
                <Route path="company" element={<MyCompanyPage />} />
                <Route path="knowledge" element={<EmployeeKnowledgeListPage />} />
                <Route
                  path="knowledge/:articleId"
                  element={<EmployeeArticlePage />}
                />
                <Route path="ai" element={<EmployeeAIPage />} />
                <Route
                  path="profile"
                  element={<SettingsPage section="profile" />}
                />
                <Route
                  path="security"
                  element={<SettingsPage section="security" />}
                />
              </Route>
            </Route>
          </Route>

          <Route path="/dashboard" element={<RoleHomeRedirect />} />
          <Route path="/profile" element={<RoleHomeRedirect />} />
          <Route path="/security" element={<RoleHomeRedirect />} />
          <Route path="/settings" element={<RoleHomeRedirect />} />
          <Route
            path="/company-settings"
            element={<Navigate to="/company/settings" replace />}
          />
          <Route path="/employees/*" element={<RoleHomeRedirect />} />
          <Route path="/onboarding/*" element={<RoleHomeRedirect />} />
          <Route path="/assignments/*" element={<RoleHomeRedirect />} />
          <Route path="/knowledge/*" element={<RoleHomeRedirect />} />
          <Route
            path="/my-onboarding"
            element={<Navigate to="/employee/onboarding" replace />}
          />
          <Route
            path="/my/active"
            element={<Navigate to="/employee/active" replace />}
          />
          <Route
            path="/my/history"
            element={<Navigate to="/employee/history" replace />}
          />
          <Route
            path="/my/calendar"
            element={<Navigate to="/employee/calendar" replace />}
          />
          <Route
            path="/my/company"
            element={<Navigate to="/employee/company" replace />}
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
