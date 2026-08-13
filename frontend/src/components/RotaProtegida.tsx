import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function RotaProtegida() {
  const { payload, carregando } = useAuth();
  if (carregando) {
    return <p>Carregando...</p>;
  }
  if (!payload) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
