(function () {
  const formLogin = document.getElementById("form-login");
  const formCambio = document.getElementById("form-cambio");
  const msgLogin = document.getElementById("msg-login");
  const msgCambio = document.getElementById("msg-cambio");
  let claveIngresada = "";

  function mostrar(caja, texto, tipo) {
    caja.className = "mensaje " + tipo;
    caja.textContent = texto;
    caja.hidden = false;
  }

  const motivo = new URLSearchParams(location.search).get("motivo");
  if (motivo === "sesion") mostrar(msgLogin, "Su sesión terminó. Ingrese nuevamente.", "info");
  if (motivo === "salida") mostrar(msgLogin, "Cerró sesión.", "info");

  // Si ya hay sesión válida y no debe cambiar la clave, ir directo al panel
  if (Sesion.token && Sesion.usuario && !Sesion.usuario.debe_cambiar_clave && !motivo) {
    location.replace("/");
  }
  if (Sesion.token && Sesion.usuario && Sesion.usuario.debe_cambiar_clave) {
    // Para cambiar la clave hay que confirmar la actual: se pide ingresar de nuevo
    Sesion.cerrar();
  }

  formLogin.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const email = document.getElementById("email").value.trim();
    const clave = document.getElementById("clave").value;
    if (!email || !clave) { mostrar(msgLogin, "Ingrese su correo y su contraseña.", "error"); return; }
    const btn = document.getElementById("btn-login");
    btn.disabled = true; btn.textContent = "Ingresando…";
    try {
      const r = await api("/auth/login", { metodo: "POST", cuerpo: { email, clave } });
      Sesion.guardar(r.access_token, r.usuario);
      claveIngresada = clave;
      if (r.usuario.debe_cambiar_clave) {
        formLogin.hidden = true;
        formCambio.hidden = false;
        document.getElementById("clave-nueva").focus();
      } else {
        location.replace("/");
      }
    } catch (e) {
      mostrar(msgLogin, e.message, "error");
    } finally {
      btn.disabled = false; btn.textContent = "Ingresar";
    }
  });

  formCambio.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const nueva = document.getElementById("clave-nueva").value;
    const repetida = document.getElementById("clave-repetida").value;
    if (nueva !== repetida) { mostrar(msgCambio, "Las contraseñas no coinciden.", "error"); return; }
    if (!claveIngresada) {
      // Se recargó la página: hay que volver a ingresar para confirmar la clave actual
      Sesion.cerrar();
      location.replace("/login.html");
      return;
    }
    const btn = document.getElementById("btn-cambio");
    btn.disabled = true;
    try {
      await api("/auth/cambiar-clave", { metodo: "POST", cuerpo: { clave_actual: claveIngresada, clave_nueva: nueva } });
      const u = Sesion.usuario; u.debe_cambiar_clave = false; Sesion.actualizarUsuario(u);
      location.replace("/");
    } catch (e) {
      mostrar(msgCambio, e.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
})();
