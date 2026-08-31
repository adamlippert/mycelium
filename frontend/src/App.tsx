import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { ToastProvider } from './components/primitives';
import Layout from './components/Layout';

// Route-level code splitting: every visitor used to download the whole app
// as one chunk, including the ten-tab admin tree that only admins can open.
const Discover = lazy(() => import('./pages/Discover'));
const Search = lazy(() => import('./pages/Search'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Library = lazy(() => import('./pages/Library'));
const Requests = lazy(() => import('./pages/Requests'));
const Wanted = lazy(() => import('./pages/Wanted'));
const Settings = lazy(() => import('./pages/Settings'));
const Login = lazy(() => import('./pages/Login'));
const Setup = lazy(() => import('./pages/Setup'));
const Manual = lazy(() => import('./pages/Manual'));
const AdminLayout = lazy(() => import('./pages/admin/AdminLayout'));

function PageFallback() {
  return <div className="py-16 text-center text-sm text-muted">Loading...</div>;
}

export default function App() {
  return (
    <ToastProvider>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />
          <Route element={<Layout />}>
            <Route index element={<Discover />} />
            <Route path="library" element={<Library />} />
            <Route path="watchlist" element={<Watchlist />} />
            <Route path="search" element={<Search />} />
            <Route path="requests" element={<Requests />} />
            <Route path="wanted" element={<Wanted />} />
            <Route path="settings" element={<Settings />} />
            <Route path="admin" element={<AdminLayout />} />
            <Route path="manual" element={<Manual />} />
            <Route path="*" element={<div className="text-center py-16 text-muted">Page not found</div>} />
          </Route>
        </Routes>
      </Suspense>
    </ToastProvider>
  );
}
