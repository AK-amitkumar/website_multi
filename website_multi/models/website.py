import openerp
from openerp import SUPERUSER_ID
from openerp.osv import orm, fields, osv
from openerp.addons.website.models.website import slugify
from openerp.addons.web.http import request
from werkzeug.exceptions import NotFound
import werkzeug

class website(orm.Model):

    _inherit = "website"

    def _get_menu_website(self, cr, uid, ids, context=None):
        res = []
        for menu in self.pool.get('website.menu').browse(cr, uid, ids, context=context):
            if menu.website_id:
                res.append(menu.website_id.id)
        # IF a menu is changed, update all websites
        return res

    def _get_menu(self, cr, uid, ids, name, arg, context=None):
        res = {}
        menu_obj = self.pool['website.menu']
        for id in ids:
            menu_domain = [
                ('parent_id', '=', False),
                ('website_id', '=', id),
            ]
            menu_ids = menu_obj.search(cr, uid, menu_domain, order='id',
                                       context=context)
            res[id] = menu_ids and menu_ids[0] or False

        return res

    _columns = {
        'menu_id': fields.function(
            _get_menu,
            relation='website.menu',
            type='many2one',
            string='Main Menu',
            store={
                'website.menu': (_get_menu_website, ['sequence', 'parent_id', 'website_id'], 10)
            }
        )
    }

    _defaults = {
        'user_id': lambda s, c, u, x: s.pool['ir.model.data'].xmlid_to_res_id(c, SUPERUSER_ID, 'base.public_user'),
        'company_id': lambda s, c, u, x: s.pool['ir.model.data'].xmlid_to_res_id(c, SUPERUSER_ID, 'base.main_company'),
    }

    def new_page(self, cr, uid, name, template='website.default_page', ispage=True, context=None):
        context = context or {}
        imd = self.pool['ir.model.data']
        view = self.pool['ir.ui.view']
        template_module, template_name = template.split('.')

        # completely arbitrary max_length
        page_name = slugify(name, max_length=50)
        page_xmlid = "%s.%s" % (template_module, page_name)

        try:
            # existing page
            imd.get_object_reference(cr, uid, template_module, page_name)
        except ValueError:
            # new page
            _, template_id = imd.get_object_reference(cr, uid, template_module, template_name)

            page_id = view.copy(cr, uid, template_id, {
                'website_id': context.get('website_id'),
                'key': page_xmlid
            }, context=context)

            page = view.browse(cr, uid, page_id, context=context)

            page.write({
                'arch': page.arch.replace(template, page_xmlid),
                'name': page_name,
                'page': ispage,
            })

        return page_xmlid

    @openerp.tools.ormcache(skiparg=4)
    def _get_current_website_id(self, cr, uid, domain_name, context=None):
        website_id = 1
        if request:
            ids = self.search(cr, uid, [('name', '=', domain_name)],
                              context=context)
            if ids:
                website_id = ids[0]
        return website_id

    def get_current_website(self, cr, uid, context=None):
        domain_name = self.get_current_host_domain(cr, uid, context=context)
        website_id = self._get_current_website_id(cr, uid, domain_name,
                                                  context=context)
        request.context['website_id'] = website_id
        return self.browse(cr, uid, website_id, context=context)

    def get_current_host_domain(self, cr, uid, context=None):
        return request.httprequest.environ.get('HTTP_HOST', '').split(':')[0]

    def public_user(self, cr, uid, context=None):
        return self.get_current_website(cr, uid, context=context).user_id

    def public_user_id(self, cr, uid, context=None):
        return self.public_user(cr, uid, context=context).id

    def get_template(self, cr, uid, ids, template, context=None):
        if not isinstance(template, (int, long)) and '.' not in template:
            template = 'website.%s' % template
        View = self.pool['ir.ui.view']
        view_id = View.get_view_id(cr, uid, template, context=context)
        if not view_id:
            raise NotFound
        return View.browse(cr, uid, view_id, context=context)


class ir_http(osv.AbstractModel):
    _inherit = 'ir.http'

    def _auth_method_public(self):
        if not request.session.uid:
            ws = self.pool['website']
            request.uid = ws.public_user_id(request.cr,
                                            openerp.SUPERUSER_ID,
                                            context=request.context)
        else:
            request.uid = request.session.uid

    def _get_converters(self):
        converters = super(ir_http, self)._get_converters()
        converters['page'] = PageMultiWebsiteConverter
        return converters


class PageMultiWebsiteConverter(werkzeug.routing.PathConverter):
    def generate(self, cr, uid, query=None, args={}, context=None):
        View = request.registry['ir.ui.view']
        dom = [('page', '=', True), '|', ('website_id', '=', request.website.id), ('website_id', '=', False)]
        views = View.search_read(cr, uid, dom, fields=['key', 'xml_id', 'priority','write_date'], order='name', context=context)

        for view in views:
            key = view['key'] or view['xml_id'] or ''
            xid = key.startswith('website.') and key[8:] or key

            if xid=='homepage': continue
            if query and query.lower() not in xid.lower(): continue
            record = {'loc': xid}
            if view['priority'] != 16:
                record['__priority'] = min(round(view['priority'] / 32.0, 1), 1)
            if view['write_date']:
                record['__lastmod'] = view['write_date'][:10]
            yield record

