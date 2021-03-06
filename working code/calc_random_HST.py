import yt
import glob
import argparse
import numpy as np

from scipy.interpolate    import interp1d
from scipy.interpolate    import interp2d
from scipy                import integrate
from scipy                import signal
from scipy                import stats
from astropy.io           import fits

from photutils import detect_sources
from pairs_fluxes import fluxes

parser = argparse.ArgumentParser(description='Process floats.')
parser.add_argument('floats', metavar='N', type=float, nargs='+', help='a float for the accumulator')
args = parser.parse_args()
external_param = np.array(args.floats)

# detectors' pixel size
HST_WFC3CAM_pixel_size = 0.13   # arcsec per pixel

# Constants 0
cm_in_pc = 3.0857e18
sun_luminosity = 3.828e33
arcsec_in_rad = 206265
c = 2.9927e10

# Cosmo params
Omega_lam = 0.7274
Omega_M_0 = 0.2726
Omega_k = 0.0
h = 0.704

# Functions to compute Angular diameter distance D_A [Mpc]
E   = lambda x: 1/np.sqrt(Omega_M_0*np.power(1+x,3)+Omega_lam+Omega_k*np.power(1+x,2))
D_m = lambda x: D_c(x)
D_c = lambda x: (9.26e27/h)*integrate.quad(E, 0, x)[0]
D_A = lambda x: D_m(x)/(1+x)/cm_in_pc/1e6  # Angular distance [Mpc]


def init_input_data(nsim, n_cyl1, n_cyl2, orient=0):

    global N_sim_2, telescope, filter_name, prj, N1, N2

    N1, N2 = int(n_cyl1), int(n_cyl2)
    N_sim_2 = int(nsim)

    if orient==0:
        prj='x'
    elif orient==1:
        prj='y'
    elif orient==2:
        prj='z'


def init_transmission_function():

    '''
    Interstellar medium transmission function
    '''

    global F_ISM

    table = np.loadtxt('data/table_transmition_ISM.dat')
    lam_rest   = table[1:,0]
    z          = table[0,1:]
    trans_coef = table[1:,1:]
    F_ISM = interp2d(z, lam_rest, trans_coef)


def init_lum_tables():

    '''
    Luminosity tables as a function of metallicity Z and stars' birth time t
    '''

    global lam_list, lookup, Z, logt

    muf_list = sorted(glob.glob("data/drt/muv.bin*"))
    lam_list = np.zeros(len(muf_list))
    lookup = np.zeros([len(muf_list), 188, 22])

    for i in range(len(muf_list)):
        f = open(muf_list[i])
        header = f.readline()
        lam_list[i] = float(header.split()[2])

        f.close()

        data = np.genfromtxt(muf_list[i], skip_header=1)
        lookup[i, :, :] = data[1:,1:]

    Z = data[0, 1:]  # metallicity [Sun_Z]
    logt = data[1:, 0]  # log10(t) [yr]


def filter_bandwidth(a, b, x):

    position_in_lam_array = []

    for i in range(0,len(x)):
        if a <=x[i] and x[i] <= b:
            if F_filter(x[i])>=0.5e-3:
                position_in_lam_array.append(i)

    return position_in_lam_array


def HST_filter_init(z, filter_name):

    '''
    Hubble Space Telescope filter initialization function
    '''

    global F_filter

    filter_b = np.loadtxt('data/filter_' + filter_name + '.dat')
    F_filter = interp1d(filter_b[:,0], filter_b[:,1],fill_value=0.0,bounds_error=False)
    a,b = np.min(filter_b[:,0]),np.max(filter_b[:,0])
    lamb_positions = filter_bandwidth(a,b,lam_list*(1+z))

    return lamb_positions


# TO CREATE MORE UNIFORM NOISE
def noise_adv_HST():

    i = 0
    while i < 1000:

        init_noise()
        init_PSF()
        f125 = signal.fftconvolve(noise125, PSF125, mode='same')/noise_std125
        f140 = signal.fftconvolve(noise140, PSF140, mode='same')/noise_std140
        f160 = signal.fftconvolve(noise160, PSF160, mode='same')/noise_std160
        fsum = f125 + f140 + f160
        inf = detect_sources(fsum, 2.3, 3)

        print(nbins, inf.nlabels)

        if inf.nlabels == 0:
            print('CONDITION IS SATISFIED')
            break

        i += 1


def init_noise():

    '''
    Procedure to create noise for specific filter and exposure time (only for JWST)
    '''

    global noise125, noise140, noise160, noise_std125, noise_std140, noise_std160

    zero_point = np.array([26.23,26.45,25.94])
    coeff = 10 ** (0.4 * (zero_point + 48.6))

    coeff_125 = 1e23 * 1e9 / coeff[0]
    coeff_140 = 1e23 * 1e9 / coeff[1]
    coeff_160 = 1e23 * 1e9 / coeff[2]

    noise = np.vstack((stats.norm.rvs(0.0,0.00275845*coeff_125,nbins*nbins),
                       stats.norm.rvs(0.0,3.26572605e-03*coeff_140,nbins*nbins),
                       stats.norm.rvs(0.0,0.00239519*coeff_160,nbins*nbins)))

    noise_std125 = np.std(noise[0,:])
    noise125 = np.reshape(noise[0,:], (nbins,nbins))
    noise_std140 = np.std(noise[1,:])
    noise140 = np.reshape(noise[1,:], (nbins,nbins))
    noise_std160 = np.std(noise[2,:])
    noise160 = np.reshape(noise[2,:], (nbins,nbins))


def init_PSF():

    '''
    Point Spread function initialization function
    '''

    global PSF125, PSF140, PSF160

    a = fits.open('data/psf_test_f125w00_psf.fits')[0].data[1:,1:]
    b = fits.open('data/psf_test_f140w00_psf.fits')[0].data[1:,1:]
    c = fits.open('data/psf_test_f160w00_psf.fits')[0].data[1:,1:]

    coords_a = np.linspace(-1.5 + 1.5/np.shape(a)[0],1.5 - 1.5/np.shape(a)[0],np.shape(a)[0])
    coords_b = np.linspace(-1.5 + 1.5/np.shape(b)[0],1.5 - 1.5/np.shape(b)[0],np.shape(b)[0])
    coords_c = np.linspace(-1.5 + 1.5/np.shape(c)[0],1.5 - 1.5/np.shape(c)[0],np.shape(c)[0])

    NNbins = int(3/HST_WFC3CAM_pixel_size)
    pix_edges = np.linspace(-1.5,1.5,NNbins+1)

    x, y = np.meshgrid(coords_a, coords_a)
    psf_f125w,X,Y = np.histogram2d(x.flatten(), y.flatten(), bins=(pix_edges, pix_edges), weights = a.flatten())
    x, y = np.meshgrid(coords_b, coords_b)
    psf_f140w,X,Y = np.histogram2d(x.flatten(), y.flatten(), bins=(pix_edges, pix_edges), weights = b.flatten())
    x, y = np.meshgrid(coords_c, coords_c)
    psf_f160w,X,Y = np.histogram2d(x.flatten(), y.flatten(), bins=(pix_edges, pix_edges), weights = c.flatten())

    PSF125 = psf_f125w
    PSF140 = psf_f140w
    PSF160 = psf_f160w


def main():

    global nbins

    # INITIALIZING DATA
    init_input_data(*external_param)
    init_lum_tables()
    init_transmission_function()

    # LOADING DATA    
    if N_sim_2==0:
        files = sorted(glob.glob('/home/kaurov/scratch/rei/code05/OUT_00002_010_080B/rei00002_010_080B_a0*/rei00002_010_080B_a0.*.art'))
    else:
        files = sorted(glob.glob('/home/kaurov/scratch/rei/random10/OUT_0000' + str(N_sim_2) +'_010_010_random/rei0000'+ str(N_sim_2) +'_010_010_random_a0*/rei0000'+ str(N_sim_2) +'_010_010_random_a0.*.art'))
    
    partition = np.linspace(0, 64, 5)[:-1]
    path = 'processed_random/' + str(N_sim_2) + '/' + prj + '/'
    telescope = 'HST'

    print('path', path)
    print(len(files))

    # BOX SIZES
    x_length = 16  # code length
    y_length = 16  # code length
    z_length = 16  # code length

    # LOADING DIFFERENT SNAPSHOTS OF ART SIMULATION (at different redshifts)
    for simulation in range(28):

        # ART SIM LOAD
        pf = yt.load(files[simulation])

        # SIMULATION INFO
        print('Loading data %i out of (%i in total)' % (simulation, len(files)))
        print(files[simulation])
        print('box size in each dimension', pf.domain_right_edge[0]/4)
        print('box size in each dimension', pf.domain_right_edge.in_units('kpc')[0]/4)

        # EXTRACTING REDSHIFT AND COMPUTING ANGULAR SIZE OF THE BOX
        redshift = pf.current_redshift
        simulation_name = str(simulation)
        theta_arcsec = (1e3 * pf.domain_right_edge.in_units('kpc')[0]/4) / (D_A(redshift) * 1e6) * arcsec_in_rad

        # CREATION NOISE AND PSF FOR A SPECIFIC CAMERA (TELESCOPE)
        nbins = int(theta_arcsec / HST_WFC3CAM_pixel_size)
        noise_adv_HST()

        # CREATING COORDS MESH
        ang = theta_arcsec/2
        pixels_ang_coords = (np.linspace(-ang, ang, nbins + 1)[1:] + np.linspace(-ang, ang, nbins + 1)[:-1])/2
        X, Y = np.meshgrid(pixels_ang_coords,pixels_ang_coords)

        # THRESHOLD FOR DETECTION
        npixels = 3

        # WRITING INFO INTO A FILE
        info = open(path + 'info_' + simulation_name + '.dat', 'a')
        info.write('--------------------\n')
        info.write('Telescope: HST\n')
        info.write('Simulation name: %d \n' %  simulation)
        info.write('Redshift: %.6f \n' % redshift)
        info.write('N of boxes to process: %d, %d\n' % (N1, N2))
        info.write('Theta [arcsec]: %.6f \n' % theta_arcsec)
        info.write('Flux threshold: %.3f, %.3f, %.3f, %.3f, %.3f \n' % (2.5, 2.75, 3.0, 3.5, 4.0))
        info.write('Npix: %.3f \n' % npixels)
        info.close()

        # PRINTING OUT INFO
        print('Simulation name = ',	simulation_name)
        print('z = %1.3e, D_A = %1.3e [Mpc], Nbins = %i' % (redshift, D_A(redshift), nbins))
        print('nbins = ', nbins)

        # LUMINOSITY DISTANCE = ANGULAR DISTANCE (1+z)**2
        lum_dist = D_A(redshift) * (1 + redshift) * (1 + redshift)

        # INTERPOLATION
        lookup_averaged = np.zeros((len(logt),len(Z),3))

        for filter_name, filter_idx in zip(['f125w', 'f140w', 'f160w'],[0,1,2]):

            lamb_positions = HST_filter_init(filter_name=filter_name,z=redshift)
            lamb_filter = lam_list[lamb_positions]
            nu = c/(lamb_filter/1e8)

            for ii in range(len(Z)):
                for jj in range(len(logt)):
                    lookup_averaged[jj, ii, filter_idx] = integrate.trapz( lookup[lamb_positions, jj, ii][::-1] * F_ISM(redshift,lamb_filter)[::-1,0] * \
                                                              F_filter(lamb_filter[::-1]*(1+redshift))/nu[::-1], nu[::-1]) * 1e23 * 1e9 * \
                                                              (1+redshift) / (4 * np.pi * np.power(lum_dist*cm_in_pc*1e6, 2)) * sun_luminosity / \
                                                              integrate.trapz( F_filter(lamb_filter[::-1]*(1+redshift))/nu[::-1], nu[::-1])
            print(filter_name, filter_idx)

        interp125 = interp2d(Z, logt, lookup_averaged[:,:,0])
        interp140 = interp2d(Z, logt, lookup_averaged[:,:,1])
        interp160 = interp2d(Z, logt, lookup_averaged[:,:,2])

        print('INTERPOLATION IS COMPLETED')

        # COMPUTATION STARTS... (4*4*4 BOXES [L=16] FULL BOX SIZE: [0:64,0:64,0:64])

        for r_x in partition[N1:N2]:
            for r_y in partition:
                for r_z in partition:
                    data = pf.box([r_x, r_y, r_z], [r_x+x_length, r_y+y_length, r_z+z_length])

                    x = np.array(data[('STAR', 'POSITION_X')] - data.center[0])
                    y = np.array(data[('STAR', 'POSITION_Y')] - data.center[1])
                    z = np.array(data[('STAR', 'POSITION_Z')] - data.center[2])

                    print('left edge', data.left_edge)
                    print('center', data.center)
                    print('right edge', data.right_edge)

                    m = data[('STAR', 'MASS')].in_units('msun')
                    met = data[('STAR', 'METALLICITY_SNIa')].in_units('Zsun') + data[('STAR', 'METALLICITY_SNII')].in_units('Zsun')
                    t = (data[('STAR', 'age')].in_units('yr'))

                    erase = np.where(t <= 0)[0]

                    x = np.delete(x, erase)
                    y = np.delete(y, erase)
                    z = np.delete(z, erase)

                    met = np.delete(met, erase)
                    t = np.log10(np.delete(t, erase))
                    m = np.delete(m, erase)

                    print('number of objects', len(t))

                    xedges = np.linspace(-x_length/2, x_length/2, nbins+1)
                    yedges = np.linspace(-y_length/2, y_length/2, nbins+1)

                    Flux = np.zeros((len(m), 3))

                    for j in range(0,len(m)):
                        Flux[j,0] = interp125(met[j], t[j])[0] * m[j]
                        Flux[j,1] = interp140(met[j], t[j])[0] * m[j]
                        Flux[j,2] = interp160(met[j], t[j])[0] * m[j]

                    if  prj == 'x':
                        H125, X1, X2 = np.histogram2d(y, z, bins=(xedges, yedges), weights = Flux[:,0])
                        H140, X1, X2 = np.histogram2d(y, z, bins=(xedges, yedges), weights = Flux[:,1])
                        H160, X1, X2 = np.histogram2d(y, z, bins=(xedges, yedges), weights = Flux[:,2])
                    elif prj == 'y':
                        H125, X1, X2 = np.histogram2d(z, x, bins=(xedges, yedges), weights = Flux[:,0])
                        H140, X1, X2 = np.histogram2d(z, x, bins=(xedges, yedges), weights = Flux[:,1])
                        H160, X1, X2 = np.histogram2d(z, x, bins=(xedges, yedges), weights = Flux[:,2])
                    elif prj == 'z':
                        H125, X1, X2 = np.histogram2d(x, y, bins=(xedges, yedges), weights = Flux[:,0])
                        H140, X1, X2 = np.histogram2d(x, y, bins=(xedges, yedges), weights = Flux[:,1])
                        H160, X1, X2 = np.histogram2d(x, y, bins=(xedges, yedges), weights = Flux[:,2])

                    flux_noise125 = np.rot90(H125) + noise125
                    flux_noise_psf125 = signal.fftconvolve(flux_noise125, PSF125, mode='same')
                    flux_noise_psf_std125 = flux_noise_psf125/noise_std125

                    flux_noise140 = np.rot90(H140) + noise140
                    flux_noise_psf140 = signal.fftconvolve(flux_noise140, PSF140, mode='same')
                    flux_noise_psf_std140 = flux_noise_psf140/noise_std140

                    flux_noise160 = np.rot90(H160) + noise160
                    flux_noise_psf160 = signal.fftconvolve(flux_noise160, PSF160, mode='same')
                    flux_noise_psf_std160 = flux_noise_psf160/noise_std160
                    
                    flux_noise_psf_std = flux_noise_psf_std125 + flux_noise_psf_std140 + flux_noise_psf_std160

                    # SOURCES DETECTION

                    for threshold,thr_number in zip([2.5, 2.75, 3, 3.5, 4], ['0', '1', '2', '3', '4']):

                        print(threshold, thr_number)
                        inf = detect_sources(flux_noise_psf_std, threshold, npixels)

                        for iso_gr, gr_dist, gr_name in zip([0, 1, 1], [3.0, 3.0, 1.0], ['_iso_', '_gr_3_', '_gr_1_']):

                            print('iso_or_gr:', iso_gr)
                            print('gr_dist:', gr_dist)
                            print('file_name:', gr_name)

                            obj_125_data = fluxes(flux_noise_psf125, np.array(inf), inf.nlabels, X, Y, group=iso_gr, dist_max=gr_dist)
                            obj_140_data = fluxes(flux_noise_psf140, np.array(inf), inf.nlabels, X, Y, group=iso_gr, dist_max=gr_dist)
                            obj_160_data = fluxes(flux_noise_psf160, np.array(inf), inf.nlabels, X, Y, group=iso_gr, dist_max=gr_dist)

                            obj_125_filename = open(path + 'objects' + gr_name + simulation_name + '_125_' + telescope + '_' + thr_number + '.dat', 'ab')
                            obj_140_filename = open(path + 'objects' + gr_name + simulation_name + '_140_' + telescope + '_' + thr_number + '.dat', 'ab')
                            obj_160_filename = open(path + 'objects' + gr_name + simulation_name + '_160_' + telescope + '_' + thr_number + '.dat', 'ab')

                            np.savetxt(obj_125_filename, np.array(obj_125_data).T,fmt='%1.5e')
                            np.savetxt(obj_140_filename, np.array(obj_140_data).T,fmt='%1.5e')
                            np.savetxt(obj_160_filename, np.array(obj_160_data).T,fmt='%1.5e')

                            obj_125_filename.close()
                            obj_140_filename.close()
                            obj_160_filename.close()

main()








