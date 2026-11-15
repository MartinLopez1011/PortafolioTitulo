(function () {
  const formLogin = document.getElementById("form-login");
  const formCambio = document.getElementById("form-cambio");
  const msgLogin = document.getElementById("msg-login");
  const msgCambio = document.getElementById("msg-cambio");
  let claveIngresada = "";

  function mostrar(caja, texto, tipo) {
    caja.className = "mensaje " + tipo;
    caja.setAttribute("role", tipo === "error" ? "alert" : "status");
    caja.textContent = texto;
    caja.hidden = false;
  }

  document.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("input", () => inp.removeAttribute("aria-invalid"));
  });

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
    const emailEl = document.getElementById("email");
    const claveEl = document.getElementById("clave");
    const email = emailEl.value.trim();
    const clave = claveEl.value;
    if (!email || !clave) {
      if (!email) emailEl.setAttribute("aria-invalid", "true");
      if (!clave) claveEl.setAttribute("aria-invalid", "true");
      mostrar(msgLogin, "Ingrese su correo y su contraseña.", "error");
      return;
    }
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
      emailEl.setAttribute("aria-invalid", "true");
      claveEl.setAttribute("aria-invalid", "true");
      mostrar(msgLogin, e.message, "error");
    } finally {
      btn.disabled = false; btn.textContent = "Ingresar";
    }
  });

  formCambio.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const nuevaEl = document.getElementById("clave-nueva");
    const repEl = document.getElementById("clave-repetida");
    const nueva = nuevaEl.value;
    const repetida = repEl.value;
    if (nueva !== repetida) {
      repEl.setAttribute("aria-invalid", "true");
      mostrar(msgCambio, "Las contraseñas no coinciden.", "error");
      return;
    }
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
