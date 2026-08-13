import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import RotaProtegida from "./components/RotaProtegida";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import SelecionarEmpresaPage from "./pages/SelecionarEmpresaPage";
import AceitarConvitePage from "./pages/AceitarConvitePage";
import CadastroEmpresaPage from "./pages/CadastroEmpresaPage";
import ClientesPage from "./pages/ClientesPage";
import ImportarCsvPage from "./pages/ImportarCsvPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/aceitar-convite" element={<AceitarConvitePage />} />
          <Route element={<RotaProtegida />}>
            <Route path="/selecionar-empresa" element={<SelecionarEmpresaPage />} />
            <Route element={<Layout />}>
              <Route path="/emissoes" element={<p>Emissoes (Task 8)</p>} />
              <Route path="/cadastro-empresa" element={<CadastroEmpresaPage />} />
              <Route path="/clientes" element={<ClientesPage />} />
              <Route path="/importar-csv" element={<ImportarCsvPage />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
