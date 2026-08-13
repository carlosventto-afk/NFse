import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import RotaProtegida from "./components/RotaProtegida";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import SelecionarEmpresaPage from "./pages/SelecionarEmpresaPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RotaProtegida />}>
            <Route path="/selecionar-empresa" element={<SelecionarEmpresaPage />} />
            <Route element={<Layout />}>
              <Route path="/emissoes" element={<p>Emissoes (Task 8)</p>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
