import { Roles } from "../../constants/roles.js";
import { routes } from "../../router/router.js";
import { el } from "../../utils/dom.js";

// Outsourced teams only see the drill module; every other role sees the normal
// workflow plus drills.
function navigation(config, role) {
  const drillLabel = config.drill_module || "演练副本";
  if (role === "outsource") {
    return [{name: "drills", label: drillLabel}];
  }
  return [
    ...routes.filter(name => name !== "drills").map((name, index) => ({name, label: config.modules[index]})),
    {name: "drills", label: drillLabel},
  ];
}

export function shell(config, user, route, page, signOut) {
  const links = navigation(config, user.role).map(({name, label}) => el("a", {
    href: `#${name}`, "aria-current": route.name === name ? "page" : null,
  }, label));
  return el("div", {class: "shell"},
    el("aside", {class: "rail"},
      el("a", {class: "brand", href: "#overview"}, config.title),
      el("p", {class: "rail-direction"}, config.direction),
      el("nav", {"aria-label": "业务模块"}, links),
      el("div", {class: "rail-user"}, el("span", {}, Roles[user.role]),
        el("button", {class: "quiet", onclick: signOut, type: "button"}, "退出"))),
    el("main", {id: "content", class: "workspace", "data-route": route.id ? `${route.name}/${route.id}` : route.name}, page));
}
